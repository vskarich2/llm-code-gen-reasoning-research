"""Generic grouped metric table rendering."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.styling import style_dataframe
from dashboard.compute_engine import compute_metrics


def render_grouped_metric_table(
    df: pd.DataFrame,
    title: str,
    metrics: list[str],
    groupby: list[str],
    sort_by: list[str] | None = None,
) -> None:
    st.subheader(title)
    result = compute_metrics(df, metrics, groupby)
    if result.empty:
        st.info("No data for this view.")
        return
    if sort_by:
        present = [c for c in sort_by if c in result.columns]
        if present:
            result = result.sort_values(present)
    st.dataframe(
        style_dataframe(result, metric_columns=[c for c in metrics if c in result.columns]),
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(result) + 38, 900),
    )
