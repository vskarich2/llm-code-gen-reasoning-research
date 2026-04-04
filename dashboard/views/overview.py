"""Overview tab: metric cards, heatmap, detailed table, cluster analysis."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.components.metrics import render_metric_cards
from dashboard.components.styling import style_dataframe
from dashboard.compute_engine import compute_metrics
from dashboard.tab_docs import abbreviate_columns, render_tab_docs


def _load_config_snapshot(exp_path: str) -> str | None:
    """Load config.snapshot.yaml from an experiment log directory."""
    p = Path(exp_path) / "config.snapshot.yaml"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def render_overview(
    df: pd.DataFrame,
    selected_experiments: list[str] | None = None,
) -> None:
    st.subheader("Overview")
    render_tab_docs("overview")

    # ── Experiment configs ──
    if selected_experiments:
        for exp_path in selected_experiments:
            config_text = _load_config_snapshot(exp_path)
            label = Path(exp_path).name
            if config_text:
                with st.expander(f"config — {label}", expanded=False):
                    st.code(config_text, language="yaml")
            else:
                st.caption(f"{label}: no config.snapshot.yaml found")

    render_metric_cards(df)

    st.markdown("---")
    st.markdown("##### Model × Condition")
    summary = compute_metrics(
        df,
        ["pass_rate", "leg_rate", "lucky_fix_rate", "reasoning_rate", "count"],
        ["model", "condition"],
    )
    if summary.empty:
        st.info("No summary data.")
        return

    selected_metric = st.selectbox(
        "Heatmap Metric",
        ["pass_rate", "leg_rate", "lucky_fix_rate", "reasoning_rate", "count"],
        index=0,
        key="overview_heatmap_metric",
    )

    pivot = summary.pivot(index="model", columns="condition", values=selected_metric).fillna(0)
    heatmap = pivot.style.format("{:.3f}" if selected_metric != "count" else "{:,.0f}").background_gradient(cmap="Blues")
    st.dataframe(heatmap, use_container_width=True)

    st.markdown("##### Detailed Table")
    metric_cols = [c for c in summary.columns if summary[c].dtype in ("float64", "int64", "float32", "int32")]
    sorted_summary = summary.sort_values(["model", "condition"])
    renamed, legend, short_names = abbreviate_columns(sorted_summary, metric_cols)
    if legend:
        st.caption(legend)
    st.dataframe(
        style_dataframe(renamed, metric_columns=short_names),
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(renamed) + 38, 800),
    )

    # ── AST + Oracle Cluster Analysis ──
    _render_cluster_analysis(df)


# ═══════════════════════════════════════════════════════════════
# CLUSTER ANALYSIS
# ═══════════════════════════════════════════════════════════════


def _render_cluster_analysis(df: pd.DataFrame) -> None:
    """AST + Oracle + Classifier cluster analysis.

    Renders BOTH oracle and classifier analyses side-by-side when both
    are available. No fallback. Each reasoning source gets its own
    complete analysis.
    """
    has_ast = "ast_status" in df.columns and df["ast_status"].notna().any()
    has_oracle = "oracle_correct" in df.columns and df["oracle_correct"].notna().any()
    # Classifier reasoning: try reasoning_sufficient (3-axis), then reasoning_correct (schema)
    classifier_col = None
    if "reasoning_sufficient" in df.columns and df["reasoning_sufficient"].notna().any():
        classifier_col = "reasoning_sufficient"
    elif "reasoning_correct" in df.columns and df["reasoning_correct"].notna().any():
        classifier_col = "reasoning_correct"
    has_classifier = classifier_col is not None
    has_exec = "exec_pass" in df.columns

    if not has_ast or not has_exec:
        return
    if not has_oracle and not has_classifier:
        return

    st.markdown("---")
    st.markdown("##### AST + Structural Cluster Analysis")

    # Build list of reasoning sources — BOTH rendered, no fallback
    sources = []
    if has_oracle:
        sources.append(("oracle_correct", "Oracle"))
    if has_classifier:
        sources.append((classifier_col, "Classifier"))

    # Render each source as its own complete analysis
    if len(sources) == 2:
        tab_oracle, tab_classifier = st.tabs(["Oracle Labels", "Classifier Labels"])
        containers = [tab_oracle, tab_classifier]
    else:
        containers = [st.container()]

    for (reasoning_col, reasoning_label), container in zip(sources, containers):
        with container:
            _render_single_cluster(df, reasoning_col, reasoning_label)


def _render_single_cluster(
    df: pd.DataFrame, reasoning_col: str, reasoning_label: str,
) -> None:
    """Render one complete cluster analysis for a single reasoning source."""
    mask = (
        df["ast_status"].isin(["correct", "incorrect"])
        & df[reasoning_col].notna()
        & df["exec_pass"].notna()
    )
    assessable = df[mask].copy()

    if len(assessable) < 10:
        st.caption(
            f"Insufficient assessable events for {reasoning_label} "
            f"cluster analysis (need 10, have {len(assessable)})."
        )
        return

    ast_ok = assessable["ast_status"] == "correct"
    reas_ok = assessable[reasoning_col].astype(bool)
    exec_ok = assessable["exec_pass"].astype(bool)

    # ── Anchor metrics ──
    n = len(assessable)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{reasoning_label} Correct", f"{reas_ok.mean():.1%}")
    c2.metric("AST Correct", f"{ast_ok.mean():.1%}")
    c3.metric("Exec Pass", f"{exec_ok.mean():.1%}")
    c4.metric("Assessable N", f"{n:,}")

    # ── Three-way decomposition ──
    st.markdown("###### Three-Way Decomposition")
    st.caption(
        f"Every assessable attempt classified by {reasoning_label} "
        f"× AST × Execution. Eight mutually exclusive categories."
    )

    cats = []
    for r, a, e, label in [
        (True, True, True, "FULL_SUCCESS"),
        (True, True, False, "EXECUTION_GAP"),
        (False, False, False, "FULL_FAILURE"),
        (False, True, True, "LUCKY_REASONING"),
        (True, False, True, "LUCKY_FIX"),
        (False, True, False, "AST_OK_REASONING_WRONG"),
        (True, False, False, "STRUCTURAL_FAILURE"),
        (False, False, True, "DOUBLE_LUCKY"),
    ]:
        count = ((reas_ok == r) & (ast_ok == a) & (exec_ok == e)).sum()
        cats.append({"Category": label, "Count": count, "%": count / n})

    decomp = pd.DataFrame(cats).sort_values("Count", ascending=False)
    st.dataframe(
        decomp.style.format({"Count": "{:,}", "%": "{:.1%}"})
        .background_gradient(subset=["%"], cmap="Blues"),
        use_container_width=True, hide_index=True,
    )

    # ── Causal failure decomposition ──
    total_fail = (~exec_ok).sum()
    if total_fail > 0:
        st.markdown("###### Causal Failure Decomposition")
        st.caption(
            "Where failures originate: reasoning first, then structure, "
            "then execution semantics."
        )
        stage_1 = (~reas_ok & ~exec_ok).sum()
        stage_2 = (reas_ok & ~ast_ok & ~exec_ok).sum()
        stage_3 = (reas_ok & ast_ok & ~exec_ok).sum()

        stages = pd.DataFrame([
            {"Stage": f"1. {reasoning_label} failure",
             "Count": stage_1, "% of failures": stage_1 / total_fail},
            {"Stage": "2. Structural failure",
             "Count": stage_2, "% of failures": stage_2 / total_fail},
            {"Stage": "3. Execution gap",
             "Count": stage_3, "% of failures": stage_3 / total_fail},
        ])
        st.dataframe(
            stages.style.format(
                {"Count": "{:,}", "% of failures": "{:.1%}"}),
            use_container_width=True, hide_index=True,
        )

    # ── Condition comparison ──
    if "condition" in assessable.columns:
        st.markdown("###### By Condition")
        cond_data = (
            assessable.groupby("condition")
            .agg(
                N=("exec_pass", "size"),
                **{f"{reasoning_label}%": (reasoning_col, lambda x: x.astype(bool).mean())},
                **{"AST%": ("ast_status", lambda x: (x == "correct").mean())},
                **{"Pass%": ("exec_pass", "mean")},
            )
            .reset_index()
        )
        cond_data["ExecGap%"] = cond_data[f"{reasoning_label}%"] - cond_data["Pass%"]
        cond_data = cond_data.sort_values("Pass%", ascending=True)
        st.dataframe(
            style_dataframe(cond_data, metric_columns=[
                "N", f"{reasoning_label}%", "AST%", "Pass%", "ExecGap%"]),
            use_container_width=True, hide_index=True,
        )

    # ── Model comparison ──
    if "model" in assessable.columns:
        st.markdown("###### By Model")
        model_data = (
            assessable.groupby("model")
            .agg(
                N=("exec_pass", "size"),
                **{f"{reasoning_label}%": (reasoning_col, lambda x: x.astype(bool).mean())},
                **{"AST%": ("ast_status", lambda x: (x == "correct").mean())},
                **{"Pass%": ("exec_pass", "mean")},
            )
            .reset_index()
        )
        model_data["ExecGap%"] = model_data[f"{reasoning_label}%"] - model_data["Pass%"]
        model_data = model_data.sort_values("ExecGap%", ascending=False)
        st.dataframe(
            style_dataframe(model_data, metric_columns=[
                "N", f"{reasoning_label}%", "AST%", "Pass%", "ExecGap%"]),
            use_container_width=True, hide_index=True,
        )

    # ── Execution gap hotspots (by case) ──
    if "case_id" in assessable.columns:
        st.markdown("###### Execution Gap Hotspots")
        st.caption(
            "Cases with highest execution gap: reasoning + structure correct "
            "but tests fail. These are the strongest LEG cases."
        )
        case_data = (
            assessable.groupby("case_id")
            .agg(
                N=("exec_pass", "size"),
                **{f"{reasoning_label}%": (reasoning_col, lambda x: x.astype(bool).mean())},
                **{"AST%": ("ast_status", lambda x: (x == "correct").mean())},
                **{"Pass%": ("exec_pass", "mean")},
            )
            .reset_index()
        )
        case_data["ExecGap%"] = (
            case_data[f"{reasoning_label}%"].clip(lower=0)
            * case_data["AST%"].clip(lower=0)
            - case_data["Pass%"]
        )
        case_data = case_data[case_data["ExecGap%"] > 0.1].sort_values(
            "ExecGap%", ascending=False).head(15)

        if len(case_data) > 0:
            if "family" in assessable.columns:
                fam_map = assessable.drop_duplicates("case_id")[
                    ["case_id", "family"]
                ].set_index("case_id")["family"]
                case_data["Family"] = case_data["case_id"].map(fam_map)
            if "difficulty" in assessable.columns:
                diff_map = assessable.drop_duplicates("case_id")[
                    ["case_id", "difficulty"]
                ].set_index("case_id")["difficulty"]
                case_data["Diff"] = case_data["case_id"].map(diff_map)

            display_cols = ["case_id"]
            if "Family" in case_data.columns:
                display_cols.append("Family")
            if "Diff" in case_data.columns:
                display_cols.append("Diff")
            display_cols += [
                "N", f"{reasoning_label}%", "AST%", "Pass%", "ExecGap%",
            ]

            st.dataframe(
                style_dataframe(
                    case_data[display_cols],
                    metric_columns=[
                        "N", f"{reasoning_label}%", "AST%",
                        "Pass%", "ExecGap%",
                    ],
                ),
                use_container_width=True, hide_index=True,
            )

