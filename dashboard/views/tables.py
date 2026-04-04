"""Generic grouped metric table rendering."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.case_reference import render_case_reference_panels
from dashboard.components.styling import style_dataframe
from dashboard.compute_engine import compute_metrics
from dashboard.tab_docs import abbreviate_columns, render_tab_docs

# Map table title to tab_docs key
_TITLE_TO_DOC_KEY = {
    "Family Breakdown": "family_breakdown",
    "Model × Condition": "model_condition",
    "Retry Analysis": "retry_analysis",
    "By Difficulty": "by_difficulty",
}


def render_grouped_metric_table(
    df: pd.DataFrame,
    title: str,
    metrics: list[str],
    groupby: list[str],
    sort_by: list[str] | None = None,
) -> None:
    st.subheader(title)
    doc_key = _TITLE_TO_DOC_KEY.get(title)
    if doc_key:
        render_tab_docs(doc_key)
    if title == "Family Breakdown":
        render_case_reference_panels()
    result = compute_metrics(df, metrics, groupby)
    if result.empty:
        st.info("No data for this view.")
        return
    if sort_by:
        present = [c for c in sort_by if c in result.columns]
        if present:
            result = result.sort_values(present)
    present_metrics = [c for c in metrics if c in result.columns]
    renamed, legend, short_names = abbreviate_columns(result, present_metrics)
    if legend:
        st.caption(legend)
    st.dataframe(
        style_dataframe(renamed, metric_columns=short_names),
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(renamed) + 38, 900),
    )
