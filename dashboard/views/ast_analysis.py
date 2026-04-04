"""AST + Structural Reasoning Page.

Displays AST structural verification signals and their relationship
to the 5-class outcome taxonomy.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.ast_tree import render_ast_tree
from dashboard.components.charts import static_bar_chart
from dashboard.components.example_detail import render_example_detail
from dashboard.components.styling import style_dataframe
from dashboard.tab_docs import render_tab_docs


def render_ast_analysis(df: pd.DataFrame) -> None:
    st.subheader("AST + Structural Reasoning Analysis")
    render_tab_docs("ast_analysis")

    if "ast_status" not in df.columns:
        st.warning("AST fields not available. No AST evaluation data in the loaded experiments.")
        return

    # ── 3.1 AST STATUS DISTRIBUTION ──
    st.markdown("##### AST Status Distribution")

    ast_dist = df["ast_status"].value_counts()
    col1, col2 = st.columns([2, 1])
    with col1:
        static_bar_chart(ast_dist)
    with col2:
        n = len(df)
        for status in ["correct", "incorrect", "unknown", "not_available", "not_measurable"]:
            count = (df["ast_status"] == status).sum()
            if count > 0:
                st.metric(status, f"{count:,} ({count/n:.1%})")

    # ── 3.2 AST VS OUTCOME CLASS ──
    st.markdown("---")
    st.markdown("##### AST Status × Outcome Class")

    if "outcome_class" in df.columns:
        cross = pd.crosstab(
            df["outcome_class"],
            df["ast_status"],
            margins=True,
        )
        st.dataframe(
            cross.style.background_gradient(cmap="Blues"),
            use_container_width=True,
        )

        # Normalized version
        cross_pct = pd.crosstab(
            df["outcome_class"],
            df["ast_status"],
            normalize="index",
        )
        st.markdown("*Row-normalized (proportion within each outcome class):*")
        st.dataframe(
            cross_pct.style.format("{:.1%}").background_gradient(cmap="Blues"),
            use_container_width=True,
        )

    # ── 3.3 STRUCTURAL CONSISTENCY METRICS ──
    st.markdown("---")
    st.markdown("##### Structural Consistency by Outcome Class")

    if "outcome_class" in df.columns and "ast_status" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            by_outcome = (
                assessable.groupby("outcome_class")
                .agg(
                    n=("ast_status", "size"),
                    ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                )
                .reset_index()
                .sort_values("ast_correct_rate", ascending=False)
            )
            st.dataframe(
                style_dataframe(by_outcome, metric_columns=["n", "ast_correct_rate"]),
                use_container_width=True,
                hide_index=True,
            )

    # ── 3.4 AST VS LEG (with subtypes) ──
    st.markdown("---")
    st.markdown("##### AST in LEG vs Non-LEG Events")

    if "LEG" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            leg_ast = assessable.groupby("LEG").agg(
                n=("ast_status", "size"),
                ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
            ).reset_index()
            leg_ast["LEG"] = leg_ast["LEG"].map({True: "LEG events", False: "Non-LEG events"})

            col_l1, col_l2 = st.columns(2)
            with col_l1:
                st.dataframe(
                    style_dataframe(leg_ast, metric_columns=["n", "ast_correct_rate"]),
                    use_container_width=True,
                    hide_index=True,
                )
            with col_l2:
                leg_only = assessable[assessable["LEG"]]
                if len(leg_only) > 0:
                    st.metric(
                        "AST Correct Rate in LEG",
                        f"{(leg_only['ast_status'] == 'correct').mean():.1%}",
                    )
                    st.caption(
                        "High AST-correct rate in LEG events indicates "
                        "the gap is execution fidelity, not structural."
                    )

            # LEG subtypes (if available)
            if "LEG_subtype" in df.columns and len(leg_only) > 0:
                leg_sub = leg_only[leg_only["LEG_subtype"].notna() & (leg_only["LEG_subtype"] != "")]
                if len(leg_sub) > 0:
                    st.markdown("###### LEG Subtypes × AST")
                    sub_ast = leg_sub.groupby("LEG_subtype").agg(
                        n=("ast_status", "size"),
                        ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                    ).reset_index()
                    st.dataframe(
                        style_dataframe(sub_ast, metric_columns=["n", "ast_correct_rate"]),
                        use_container_width=True, hide_index=True,
                    )
                    st.caption(
                        "**execution_failure**: reasoning + translation OK, code just doesn't work. "
                        "**translation_failure**: reasoning OK but code doesn't match reasoning."
                    )

    # ── 3.4b AST × CLASSIFIER CONSISTENCY ──
    _v3_dim_cols = {
        "RIC": "reasoning_internal_consistency",
        "CIC": "commitments_internal_consistency",
        "CCC": "commitments_code_consistency",
        "RCA": "reasoning_code_alignment",
    }
    v3_available = {k: v for k, v in _v3_dim_cols.items()
                    if v in df.columns and df[v].notna().any()}
    if v3_available:
        st.markdown("---")
        st.markdown("##### AST × Classifier Dimensions")
        st.markdown(
            "The blind classifier evaluates **internal consistency** (not correctness) across four dimensions:\n\n"
            "| Abbrev | Full Name | Question |\n"
            "|--------|-----------|----------|\n"
            "| **RIC** | reasoning_internal_consistency | Does the root cause logically support the fix strategy? |\n"
            "| **CIC** | commitments_internal_consistency | Do the code commitments follow from the fix strategy? |\n"
            "| **CCC** | commitments_code_consistency | Does the generated code implement the stated commitments? |\n"
            "| **RCA** | reasoning_code_alignment | Does the generated code match the stated fix strategy? |\n\n"
            "The **Translation axis (T)** is derived as T = RIC ∧ CCC. "
            "High AST + low CCC = model built the right structure but commitments weren't fully implemented."
        )
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            rows = []
            for short, col in v3_available.items():
                correct_vals = assessable[assessable[col] == "CORRECT"]
                incorrect_vals = assessable[assessable[col] == "INCORRECT"]
                rows.append({
                    "Dimension": short,
                    "N": assessable[col].notna().sum(),
                    "CORRECT": len(correct_vals),
                    "INCORRECT": len(incorrect_vals),
                    "AST correct when dim=CORRECT": (
                        (correct_vals["ast_status"] == "correct").mean()
                        if len(correct_vals) > 0 else None
                    ),
                    "AST correct when dim=INCORRECT": (
                        (incorrect_vals["ast_status"] == "correct").mean()
                        if len(incorrect_vals) > 0 else None
                    ),
                })
            dim_df = pd.DataFrame(rows)
            fmt = {
                "AST correct when dim=CORRECT": "{:.1%}",
                "AST correct when dim=INCORRECT": "{:.1%}",
            }
            st.dataframe(
                dim_df.style.format(fmt, na_rep="—"),
                use_container_width=True, hide_index=True,
            )

    # ── 3.4c AST × ORACLE ──
    has_oracle = "oracle_correct" in df.columns and df["oracle_correct"].notna().any()
    if has_oracle:
        st.markdown("---")
        st.markdown("##### AST × Oracle Reasoning")
        st.caption(
            "How AST structural correctness relates to oracle reasoning labels. "
            "AST correct + oracle correct + exec fail = strongest LEG signal."
        )
        assessable = df[
            df["ast_status"].isin(["correct", "incorrect"])
            & df["oracle_correct"].notna()
        ]
        if len(assessable) > 0:
            cross = pd.crosstab(
                assessable["oracle_correct"].map({True: "Oracle CORRECT", False: "Oracle INCORRECT"}),
                assessable["ast_status"],
                margins=True,
            )
            st.dataframe(
                cross.style.background_gradient(cmap="Blues"),
                use_container_width=True,
            )

    # ── AST BY MODEL ──
    st.markdown("---")
    st.markdown("##### AST Correct Rate by Model")

    if "model" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            by_model = (
                assessable.groupby("model")
                .agg(
                    n=("ast_status", "size"),
                    ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                    exec_pass_rate=("exec_pass", lambda x: x.fillna(False).mean()),
                )
                .reset_index()
                .sort_values("ast_correct_rate", ascending=False)
            )
            st.dataframe(
                style_dataframe(by_model, metric_columns=["n", "ast_correct_rate", "exec_pass_rate"]),
                use_container_width=True,
                hide_index=True,
            )

    # ── AST BY FAMILY ──
    st.markdown("---")
    st.markdown("##### AST Correct Rate by Family")

    if "family" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            by_family = (
                assessable.groupby("family")
                .agg(
                    n=("ast_status", "size"),
                    ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                    exec_pass_rate=("exec_pass", lambda x: x.fillna(False).mean()),
                    exec_gap=("ast_status", lambda x: (
                        ((x == "correct") & ~assessable.loc[x.index, "exec_pass"].fillna(False)).mean()
                    )),
                )
                .reset_index()
                .sort_values("exec_gap", ascending=False)
            )
            st.dataframe(
                style_dataframe(by_family, metric_columns=["n", "ast_correct_rate", "exec_pass_rate", "exec_gap"]),
                use_container_width=True,
                hide_index=True,
                height=min(38 * len(by_family) + 38, 800),
            )

    # ── 3.5 AST EXAMPLES WITH TREE VISUALIZATION ──
    st.markdown("---")
    st.markdown("##### AST Example Events")
    st.caption(
        "Each example shows the parsed AST structure alongside the "
        "generated code and checker results. The AST tree reveals "
        "what the model built structurally — independent of whether "
        "the logic inside is correct."
    )

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        ast_filter = st.selectbox(
            "Filter by AST status",
            ["correct", "incorrect", "unknown", "not_available", "all"],
            key="ast_example_filter",
        )
    with col_f2:
        outcome_choices = ["all", "LEG", "interpretable_success",
                          "serialization_failure", "lucky_fix",
                          "coherent_incorrect", "incoherent_incorrect"]
        # Add legacy classes if present in data
        if "outcome_class" in df.columns:
            actual = df["outcome_class"].dropna().unique().tolist()
            for oc in actual:
                if oc not in outcome_choices and oc != "all":
                    outcome_choices.append(oc)
        outcome_filter = st.selectbox(
            "Filter by outcome class",
            outcome_choices,
            key="ast_example_outcome",
        )

    if ast_filter == "all":
        filtered = df
    else:
        filtered = df[df["ast_status"] == ast_filter]

    if outcome_filter != "all" and "outcome_class" in filtered.columns:
        filtered = filtered[filtered["outcome_class"] == outcome_filter]

    n_examples = min(10, len(filtered))
    if n_examples > 0:
        sample = filtered.sample(n_examples, random_state=42)
        display_cols = [
            c for c in [
                "case_id", "model", "condition", "ast_status",
                "outcome_class", "exec_pass",
                "reasoning_internal_consistency",
                "commitments_code_consistency",
                "reasoning_code_alignment",
                "oracle_correct",
            ]
            if c in sample.columns
        ]
        # Fallback to v2 mechanism_dim if v3 not available
        if "reasoning_internal_consistency" not in sample.columns and "mechanism_dim" in sample.columns:
            display_cols = [c if c != "reasoning_internal_consistency" else "mechanism_dim"
                           for c in display_cols]
        st.dataframe(sample[display_cols], use_container_width=True,
                      hide_index=True)

        for idx, row in sample.iterrows():
            case_id = row.get("case_id", "?")
            model = row.get("model", "?")
            ast_st = row.get("ast_status", "?")
            oc = row.get("outcome_class", "")
            label = f"{case_id} | {model} | AST: {ast_st}"
            if oc:
                label += f" | {oc}"

            with st.expander(label):
                _render_ast_example(row, oc)
    else:
        st.info("No events matching the selected filters.")


def _render_ast_example(row: pd.Series, outcome_class: str) -> None:
    """Render one AST example with tree, classifier dims, oracle, and code."""
    # ── Header metrics ──
    cols = st.columns(4)
    cols[0].markdown(f"**AST:** {row.get('ast_status', '—')}")
    cols[1].markdown(f"**Execution:** {'PASS' if row.get('exec_pass') else 'FAIL'}")
    oracle = row.get("oracle_correct")
    oracle_str = "CORRECT" if oracle is True else "INCORRECT" if oracle is False else "—"
    cols[2].markdown(f"**Oracle:** {oracle_str}")
    cols[3].markdown(f"**Outcome:** {row.get('outcome_class', '—')}")

    # ── Classifier dimensions ──
    _dims = [
        ("RIC", "reasoning_internal_consistency", "Reasoning ↔ Strategy"),
        ("CIC", "commitments_internal_consistency", "Commitments ↔ Strategy"),
        ("CCC", "commitments_code_consistency", "Commitments ↔ Code"),
        ("RCA", "reasoning_code_alignment", "Strategy ↔ Code"),
    ]
    has_v3 = any(
        row.get(col) and pd.notna(row.get(col))
        for _, col, _ in _dims
    )
    if has_v3:
        dim_cols = st.columns(4)
        for i, (short, col, label) in enumerate(_dims):
            val = row.get(col, "—")
            if pd.isna(val):
                val = "—"
            dim_cols[i].markdown(f"**{short}:** {val}")

        # Justifications (collapsed)
        justifications = []
        for _, col, label in _dims:
            j = row.get(f"{col}_justification", "")
            if j and pd.notna(j) and str(j).strip():
                justifications.append((label, str(j).strip()))
        if justifications:
            with st.expander("Classifier justifications"):
                for label, text in justifications:
                    st.markdown(f"**{label}:** {text}")
    else:
        # V2 fallback
        mech = row.get("mechanism_dim", "—")
        if pd.isna(mech):
            mech = "—"
        st.markdown(f"**Mechanism (v2):** {mech}")

    # ── AST checker diagnostic ──
    diag = row.get("ast_diagnostic", "")
    if diag and pd.notna(diag) and str(diag).strip():
        st.markdown(f"**AST Checker:** {diag}")

    code = row.get("_extracted_code")
    has_code = code and pd.notna(code) and str(code).strip()

    if has_code:
        code_str = str(code)
        ast_tree = render_ast_tree(code_str)

        col_tree, col_code = st.columns([1, 1])

        with col_tree:
            st.markdown("**Structural Summary** (functions, args, key calls)")
            st.code(ast_tree, language="text")

        with col_code:
            st.markdown("**Generated Code**")
            st.code(code_str[:5000], language="python")
    else:
        st.warning("No extracted code available for AST analysis.")

    # ── Outcome-specific context ──
    render_example_detail(row, outcome_class)
