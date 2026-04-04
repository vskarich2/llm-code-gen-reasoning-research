"""LEG Benchmark Dashboard — redesigned Streamlit app.

Pipeline-aware dashboard schema:
- Overview
- Three-Axis Evaluation (5-class taxonomy)
- Failure Decomposition
- Case Explorer
- Pipeline Trace
- AST + Structural Reasoning
- Family Breakdown
- Oracle
- Field Introspection

Launch:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd
import streamlit as st

from dashboard.components.sidebar import render_sidebar
from dashboard.data.evaluation_fields import apply_evaluation_fields
from dashboard.data.filters import apply_filters, build_global_filters
from dashboard.data.loaders import load_experiment, load_oracle_labels, merge_oracle
from dashboard.data.transforms import add_failure_stage_columns
from dashboard.views.ast_analysis import render_ast_analysis
from dashboard.views.case_explorer import render_case_explorer
from dashboard.views.failure import render_failure_decomposition
from dashboard.views.oracle import render_field_introspection, render_oracle, render_oracle_only_mode
from dashboard.views.overview import render_overview
from dashboard.views.pipeline_trace import render_pipeline_trace
from dashboard.views.tables import render_grouped_metric_table
from dashboard.views.failure_taxonomy import render_failure_taxonomy
from dashboard.views.live_run import render_live_run

st.set_page_config(
    page_title="LEG Benchmark Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

TAB_ORDER = [
    "Live Run",
    "Overview",
    "Failure Taxonomy",
    "Failure Decomposition",
    "Case Explorer",
    "Pipeline Trace",
    "AST Analysis",
    "Family Breakdown",
    "Model × Condition",
    "Retry Analysis",
    "By Difficulty",
    "Oracle",
    "Field Introspection",
]


def render_header(df: pd.DataFrame) -> None:
    parts = [
        f"**{len(df):,} attempts**",
        f"**{df['chain_id'].nunique():,} chains**" if "chain_id" in df.columns else None,
        f"**{df['model'].nunique():,} models**" if "model" in df.columns else None,
        f"**{df['condition'].nunique():,} conditions**" if "condition" in df.columns else None,
        f"**{df['case_id'].nunique():,} cases**" if "case_id" in df.columns else None,
    ]
    if "oracle_verdict" in df.columns:
        labeled = df["oracle_verdict"].notna().sum()
        parts.append(f"**{labeled:,} oracle labels**")
    if "outcome_class" in df.columns:
        leg_count = (df["outcome_class"] == "LEG").sum()
        parts.append(f"**{leg_count:,} LEG events**")
    st.markdown(" | ".join([p for p in parts if p]))


def main() -> None:
    selected_experiments, selected_oracle, live_mode, poll_interval = render_sidebar()

    if not selected_experiments and not selected_oracle:
        st.info("Select experiments or oracle labels from the sidebar.")
        return

    dfs: list[pd.DataFrame] = []
    for exp in selected_experiments:
        try:
            dfs.append(load_experiment(exp))
        except Exception as exc:
            st.error(f"Failed to load {exp}: {exc}")

    oracle_df = load_oracle_labels(selected_oracle) if selected_oracle else None

    if not dfs and oracle_df is not None:
        render_oracle_only_mode(oracle_df, live_mode, poll_interval)
        return

    if not dfs:
        st.warning("No experiment data loaded.")
        return

    df = pd.concat(dfs, ignore_index=True)
    df = merge_oracle(df, oracle_df)
    df = add_failure_stage_columns(df)
    df = apply_evaluation_fields(df)

    filters = build_global_filters(df)
    filtered = apply_filters(df, filters)

    if filtered.empty:
        st.warning("The current filters removed all rows.")
        return

    render_header(filtered)

    tabs = st.tabs(TAB_ORDER)

    with tabs[0]:
        render_live_run(selected_experiments)

    with tabs[1]:
        render_overview(filtered, selected_experiments)

    with tabs[2]:
        render_failure_taxonomy(filtered)

    with tabs[3]:
        render_failure_decomposition(filtered)

    with tabs[4]:
        render_case_explorer(filtered)

    with tabs[5]:
        render_pipeline_trace(filtered)

    with tabs[6]:
        render_ast_analysis(filtered)

    with tabs[7]:
        render_grouped_metric_table(
            filtered,
            "Family Breakdown",
            ["pass_rate", "leg_rate", "lucky_fix_rate", "reasoning_rate", "count"],
            ["model", "condition", "family"],
            sort_by=["model", "condition", "family"],
        )

    with tabs[8]:
        render_grouped_metric_table(
            filtered,
            "Model × Condition",
            ["pass_rate", "leg_rate", "lucky_fix_rate", "reasoning_rate", "count"],
            ["model", "condition"],
            sort_by=["model", "condition"],
        )

    with tabs[9]:
        render_grouped_metric_table(
            filtered,
            "Retry Analysis",
            ["pass_rate", "retry_recovery_rate", "avg_attempts", "pct_improved", "pct_degraded", "count"],
            ["model", "condition"],
            sort_by=["model", "condition"],
        )

    with tabs[10]:
        render_grouped_metric_table(
            filtered,
            "By Difficulty",
            ["pass_rate", "leg_rate", "lucky_fix_rate", "reasoning_rate", "count"],
            ["model", "difficulty"],
            sort_by=["model", "difficulty"],
        )

    with tabs[11]:
        render_oracle(filtered)

    with tabs[12]:
        render_field_introspection(filtered)

    if live_mode:
        time.sleep(poll_interval)
        st.cache_data.clear()
        st.rerun()


if __name__ == "__main__":
    main()
