"""Oracle tab + oracle-only mode."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.charts import static_bar_chart
from dashboard.components.styling import style_dataframe, style_field_introspection_table
from dashboard.derived_fields import DERIVED_FIELDS
from dashboard.schema import FIELD_REGISTRY
from dashboard.tab_docs import render_tab_docs


def _resolve_oracle_column(df: pd.DataFrame) -> tuple[str | None, str]:
    """Find the oracle verdict column and its source.

    Returns (column_name, source_label) or (None, "") if no oracle data.
    Priority: inline oracle > sidebar oracle labels.
    """
    if "oracle_reasoning_truth" in df.columns and df["oracle_reasoning_truth"].notna().any():
        return "oracle_reasoning_truth", "inline oracle (v3.1)"
    if "oracle_verdict" in df.columns and df["oracle_verdict"].notna().any():
        return "oracle_verdict", "offline oracle labels"
    return None, ""


def _pct(n: int, total: int) -> str:
    return f"{n:,} ({100 * n / total:.1f}%)" if total else "0"


def _quadrant_examples(df: pd.DataFrame, verdict_col: str,
                       oracle_val: bool, exec_val: bool, max_n: int = 5) -> pd.DataFrame:
    """Get up to max_n example rows for an oracle x execution quadrant."""
    mask = pd.Series(True, index=df.index)
    if "oracle_correct" in df.columns:
        mask &= df["oracle_correct"] == oracle_val
    else:
        if oracle_val:
            mask &= df[verdict_col].isin(["CORRECT", "PARTIAL"])
        else:
            mask &= df[verdict_col].isin(["WRONG"])
    if "exec_pass" in df.columns:
        mask &= df["exec_pass"] == exec_val
    elif "pass" in df.columns:
        mask &= df["pass"] == exec_val
    subset = df[mask].head(max_n)
    cols_to_show = ["case_id", "model", "condition", verdict_col]
    if "exec_pass" in df.columns:
        cols_to_show.append("exec_pass")
    if "ast_status" in df.columns:
        cols_to_show.append("ast_status")
    # V3 classifier dims
    for col in ["reasoning_internal_consistency", "commitments_code_consistency",
                "reasoning_code_alignment"]:
        if col in df.columns:
            cols_to_show.append(col)
    return subset[[c for c in cols_to_show if c in subset.columns]]


def render_oracle(df: pd.DataFrame) -> None:
    st.subheader("Oracle")
    render_tab_docs("oracle")

    verdict_col, source_label = _resolve_oracle_column(df)
    if verdict_col is None:
        st.info("No oracle data available. Load an experiment with inline oracle enabled, "
                "or load offline oracle labels from the sidebar.")
        return

    st.caption(f"Source: **{source_label}**")

    valid = df[df[verdict_col].notna()].copy()
    if valid.empty:
        st.info("Oracle data exists but did not match the filtered rows.")
        return

    verdicts = valid[verdict_col]
    total = len(valid)
    judged = valid[verdicts != "UNJUDGABLE"]
    n_judged = len(judged)
    correct_n = int((verdicts == "CORRECT").sum())
    partial_n = int((verdicts == "PARTIAL").sum())
    wrong_n = int((verdicts == "WRONG").sum())
    unjudgable_n = int((verdicts == "UNJUDGABLE").sum())
    lenient_correct = correct_n + partial_n
    lenient_pct = lenient_correct / n_judged if n_judged else 0
    strict_pct = correct_n / n_judged if n_judged else 0

    # ── Top metrics ──
    cols = st.columns(5)
    cols[0].metric("Evaluated", f"{total:,}")
    cols[1].metric("Correct (lenient)", f"{lenient_pct:.1%}")
    cols[2].metric("Correct (strict)", f"{strict_pct:.1%}")
    cols[3].metric("WRONG", f"{wrong_n:,} ({100 * wrong_n / total:.1f}%)")
    cols[4].metric("UNJUDGABLE", f"{unjudgable_n:,}")

    # ── Verdict distribution ──
    st.markdown("##### Verdict Distribution")
    overall = pd.DataFrame({
        "Verdict": ["CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"],
        "Count": [correct_n, partial_n, wrong_n, unjudgable_n],
        "Pct": [f"{100 * correct_n / total:.1f}%", f"{100 * partial_n / total:.1f}%",
                f"{100 * wrong_n / total:.1f}%", f"{100 * unjudgable_n / total:.1f}%"],
    })
    st.dataframe(overall, use_container_width=True, hide_index=True)

    # ── Oracle x Execution quadrants ──
    st.markdown("##### Oracle x Execution Quadrants")
    has_exec = "exec_pass" in valid.columns

    if has_exec:
        exec_pass = valid["exec_pass"].fillna(False).astype(bool)
        oracle_correct = valid.get("oracle_correct", verdicts.isin(["CORRECT", "PARTIAL"])).fillna(False).astype(bool)

        oc_ep = int((oracle_correct & exec_pass).sum())
        oc_ef = int((oracle_correct & ~exec_pass).sum())
        ow_ep = int((~oracle_correct & exec_pass).sum())
        ow_ef = int((~oracle_correct & ~exec_pass).sum())

        quad = pd.DataFrame({
            "Quadrant": ["Interpretable Success (O+ E+)", "LEG (O+ E-)",
                         "Lucky Fix (O- E+)", "Reasoning Failure (O- E-)"],
            "Count": [oc_ep, oc_ef, ow_ep, ow_ef],
            "Pct": [f"{100 * oc_ep / total:.1f}%", f"{100 * oc_ef / total:.1f}%",
                    f"{100 * ow_ep / total:.1f}%", f"{100 * ow_ef / total:.1f}%"],
        })
        st.dataframe(quad, use_container_width=True, hide_index=True)

        # Example events per quadrant
        for label, o_val, e_val in [
            ("Interpretable Success (O+ E+)", True, True),
            ("LEG (O+ E-)", True, False),
            ("Lucky Fix (O- E+)", False, True),
            ("Reasoning Failure (O- E-)", False, False),
        ]:
            examples = _quadrant_examples(valid, verdict_col, o_val, e_val, max_n=5)
            if not examples.empty:
                with st.expander(f"{label} — {len(examples)} examples"):
                    st.dataframe(examples, use_container_width=True, hide_index=True)

    # ── Oracle × Classifier Dimension Agreement ──
    _v3_dims = {
        "RIC": "reasoning_internal_consistency",
        "CIC": "commitments_internal_consistency",
        "CCC": "commitments_code_consistency",
        "RCA": "reasoning_code_alignment",
    }
    v3_avail = {k: v for k, v in _v3_dims.items()
                if v in valid.columns and valid[v].notna().any()}
    if v3_avail and has_exec:
        st.markdown("##### Oracle × Classifier Dimensions")
        st.caption(
            "Agreement between oracle reasoning judgment and each classifier dimension. "
            "Low agreement on a dimension = that dimension measures something different from oracle."
        )
        oracle_c = valid.get("oracle_correct", verdicts.isin(["CORRECT", "PARTIAL"])).astype(bool)
        dim_rows = []
        for short, col in v3_avail.items():
            dim_correct = valid[col] == "CORRECT"
            both_agree = ((oracle_c & dim_correct) | (~oracle_c & ~dim_correct)).sum()
            n_both = oracle_c.notna().sum()
            dim_rows.append({
                "Dimension": short,
                "Agreement": both_agree / n_both if n_both else 0,
                "Oracle+ Dim+": int((oracle_c & dim_correct).sum()),
                "Oracle+ Dim-": int((oracle_c & ~dim_correct).sum()),
                "Oracle- Dim+": int((~oracle_c & dim_correct).sum()),
                "Oracle- Dim-": int((~oracle_c & ~dim_correct).sum()),
            })
        dim_agree_df = pd.DataFrame(dim_rows)
        st.dataframe(
            dim_agree_df.style.format({"Agreement": "{:.1%}"}),
            use_container_width=True, hide_index=True,
        )

    # ── 3-Way Decomposition (Oracle × Classifier × Execution) ──
    if v3_avail and has_exec:
        st.markdown("##### Oracle × Translation × Execution")
        st.caption(
            "T = translation consistency (RIC=CORRECT AND CCC=CORRECT). "
            "R = oracle reasoning correct. E = execution pass."
        )
        oracle_c = valid.get("oracle_correct", verdicts.isin(["CORRECT", "PARTIAL"])).astype(bool)
        exec_p = valid["exec_pass"].fillna(False).astype(bool)

        ric_col = v3_avail.get("RIC")
        ccc_col = v3_avail.get("CCC")
        if ric_col and ccc_col:
            t_bool = (valid[ric_col] == "CORRECT") & (valid[ccc_col] == "CORRECT")
            n_3way = len(valid)
            cats = []
            for r, t, e, label in [
                (True, True, True, "R+ T+ E+ (full success)"),
                (True, True, False, "R+ T+ E- (execution gap / LEG)"),
                (True, False, True, "R+ T- E+ (lucky translation)"),
                (True, False, False, "R+ T- E- (translation failure)"),
                (False, True, True, "R- T+ E+ (lucky fix)"),
                (False, True, False, "R- T+ E- (coherent incorrect)"),
                (False, False, True, "R- T- E+ (double lucky)"),
                (False, False, False, "R- T- E- (full failure)"),
            ]:
                count = int(((oracle_c == r) & (t_bool == t) & (exec_p == e)).sum())
                cats.append({"Category": label, "Count": count,
                             "%": count / n_3way if n_3way else 0})
            decomp = pd.DataFrame(cats).sort_values("Count", ascending=False)
            st.dataframe(
                decomp.style.format({"Count": "{:,}", "%": "{:.1%}"})
                .background_gradient(subset=["%"], cmap="Blues"),
                use_container_width=True, hide_index=True,
            )

    # ── LEG Subtypes ──
    if "LEG_subtype" in valid.columns and valid["LEG_subtype"].notna().any():
        leg_events = valid[valid.get("LEG", valid.get("outcome_class") == "LEG") == True]
        if len(leg_events) > 0:
            st.markdown("##### LEG Subtypes")
            st.caption(
                "**execution_failure**: reasoning + translation correct, code fails tests. "
                "**translation_failure**: reasoning correct but code doesn't match reasoning."
            )
            sub_counts = leg_events["LEG_subtype"].value_counts()
            sub_df = sub_counts.reset_index()
            sub_df.columns = ["Subtype", "Count"]
            sub_df["Pct"] = sub_df["Count"].apply(
                lambda x: f"{100 * x / len(leg_events):.1f}%")

            # Add AST correct rate per subtype if available
            if "ast_status" in leg_events.columns:
                ast_rates = []
                for subtype in sub_df["Subtype"]:
                    sub_rows = leg_events[leg_events["LEG_subtype"] == subtype]
                    measurable = sub_rows[sub_rows["ast_status"].isin(["correct", "incorrect"])]
                    if len(measurable) > 0:
                        ast_rates.append(f"{(measurable['ast_status'] == 'correct').mean():.1%}")
                    else:
                        ast_rates.append("—")
                sub_df["AST Correct"] = ast_rates

            st.dataframe(sub_df, use_container_width=True, hide_index=True)

    # ── Oracle x AST comparison ──
    st.markdown("##### Oracle x AST Comparison")
    has_ast = "ast_status" in valid.columns
    if has_ast:
        # Accept both normalized ("correct"/"incorrect") and raw ("measured_correct"/"measured_incorrect")
        ast_measured = valid[valid["ast_status"].isin(
            ["correct", "incorrect", "measured_correct", "measured_incorrect"])]
        if not ast_measured.empty:
            ast_correct = ast_measured["ast_status"].isin(["correct", "measured_correct"])
            oracle_c = ast_measured.get("oracle_correct",
                                        ast_measured[verdict_col].isin(["CORRECT", "PARTIAL"]))
            n_both = len(ast_measured)
            oc_ac = int((oracle_c & ast_correct).sum())
            oc_ai = int((oracle_c & ~ast_correct).sum())
            ow_ac = int((~oracle_c & ast_correct).sum())
            ow_ai = int((~oracle_c & ~ast_correct).sum())

            oxa = pd.DataFrame({
                "Quadrant": ["Oracle+ AST+ (reasoning & structure correct)",
                             "Oracle+ AST- (reasoning correct, structure wrong)",
                             "Oracle- AST+ (structure correct, reasoning wrong)",
                             "Oracle- AST- (both wrong)"],
                "Count": [oc_ac, oc_ai, ow_ac, ow_ai],
                "Pct": [f"{100 * oc_ac / n_both:.1f}%", f"{100 * oc_ai / n_both:.1f}%",
                        f"{100 * ow_ac / n_both:.1f}%", f"{100 * ow_ai / n_both:.1f}%"],
            })
            st.dataframe(oxa, use_container_width=True, hide_index=True)

            ast_pct = int(ast_correct.sum()) / n_both if n_both else 0
            oracle_pct = int(oracle_c.sum()) / n_both if n_both else 0
            st.markdown(
                f"AST correct: **{ast_pct:.1%}** vs Oracle correct: **{oracle_pct:.1%}** "
                f"(on {n_both:,} AST-measurable events)")
        else:
            st.caption("No AST-measurable events in this selection.")
    else:
        st.caption("AST data not available.")

    # ── Disagreement ──
    if "reasoning_disagreement_type" in valid.columns and valid["reasoning_disagreement_type"].notna().any():
        st.markdown("##### Classifier-Oracle Disagreement")
        d_counts = valid["reasoning_disagreement_type"].value_counts()
        d_total = d_counts.sum()
        d_df = d_counts.reset_index()
        d_df.columns = ["Type", "Count"]
        d_df["Pct"] = d_df["Count"].apply(lambda x: f"{100 * x / d_total:.1f}%")
        st.dataframe(d_df, use_container_width=True, hide_index=True)

    # ── By Model ──
    st.markdown("##### By Model")
    _render_breakdown(valid, "model", verdict_col, total)

    # ── By Condition ──
    st.markdown("##### By Condition")
    _render_breakdown(valid, "condition", verdict_col, total)

    # ── By Family ──
    if "family" in valid.columns and valid["family"].notna().any():
        st.markdown("##### By Family")
        _render_breakdown(valid, "family", verdict_col, total)


def _render_breakdown(df: pd.DataFrame, group_col: str,
                      verdict_col: str, total: int) -> None:
    """Render a verdict breakdown table with counts, percentages, and exec pass."""
    grouped = df.groupby(group_col)
    rows = []
    has_exec = "exec_pass" in df.columns
    for name, grp in sorted(grouped, key=lambda x: x[0]):
        n = len(grp)
        verdicts = grp[verdict_col]
        correct = int((verdicts == "CORRECT").sum())
        partial = int((verdicts == "PARTIAL").sum())
        wrong = int((verdicts == "WRONG").sum())
        lenient = correct + partial
        lenient_pct = lenient / n if n else 0
        row = {
            group_col: name,
            "N": n,
            "Oracle%": f"{lenient_pct:.1%}",
        }
        if has_exec:
            pass_rate = grp["exec_pass"].fillna(False).mean()
            row["Pass%"] = f"{pass_rate:.1%}"
            row["ExecGap"] = f"{lenient_pct - pass_rate:.1%}" if lenient_pct > pass_rate else "—"
        row["CORRECT"] = correct
        row["PARTIAL"] = partial
        row["WRONG"] = wrong
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_field_introspection(df: pd.DataFrame) -> None:
    st.subheader("Field Introspection")
    render_tab_docs("field_introspection")

    rows: list[dict[str, Any]] = []
    for column in sorted(df.columns):
        series = df[column]
        try:
            unique = int(series.nunique())
        except TypeError:
            unique = 0
        try:
            sample = series.dropna().iloc[:3].tolist() if series.notna().any() else []
        except TypeError:
            sample = ["(unrenderable)"]
        source = "derived"
        if column in FIELD_REGISTRY:
            source = FIELD_REGISTRY[column]["source"]
        elif column in DERIVED_FIELDS:
            source = "derived"

        sample_text = str(sample)
        rows.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "null_%": round(float(series.isna().mean() * 100), 1),
                "unique": unique,
                "source": source,
                "sample": sample_text[:77] + "..." if len(sample_text) > 80 else sample_text,
            }
        )

    intro = pd.DataFrame(rows)

    only_problematic = st.checkbox(
        "Show only problematic columns",
        value=False,
        key="field_introspection_problematic_only",
    )
    if only_problematic:
        intro = intro[
            (intro["null_%"] > 10)
            | (intro["unique"] == 1)
            | intro["column"].str.contains("error|parse|fail", case=False, na=False)
        ]

    st.dataframe(
        style_field_introspection_table(intro),
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(intro) + 38, 1200),
    )


def render_oracle_only_mode(oracle_df: pd.DataFrame, live_mode: bool, poll_interval: int) -> None:
    st.markdown(
        " | ".join(
            [
                f"**{len(oracle_df):,} oracle labels**",
                f"**{oracle_df['model'].nunique():,} models**" if "model" in oracle_df.columns else "",
                f"**{oracle_df['condition'].nunique():,} conditions**" if "condition" in oracle_df.columns else "",
                f"**{oracle_df['case_id'].nunique():,} cases**" if "case_id" in oracle_df.columns else "",
            ]
        )
    )
    tabs = st.tabs(["Oracle", "Field Introspection"])
    with tabs[0]:
        render_oracle(oracle_df)
    with tabs[1]:
        render_field_introspection(oracle_df)
    if live_mode:
        time.sleep(poll_interval)
        st.cache_data.clear()
        st.rerun()
