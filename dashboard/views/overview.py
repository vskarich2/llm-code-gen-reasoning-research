"""Overview tab: metric cards, heatmap, detailed table."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.metrics import render_metric_cards
from dashboard.components.styling import style_dataframe
from dashboard.compute_engine import compute_metrics


def render_overview(df: pd.DataFrame) -> None:
    st.subheader("Overview")
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
    st.dataframe(
        style_dataframe(
            summary.sort_values(["model", "condition"]),
            metric_columns=[c for c in summary.columns if summary[c].dtype in ("float64", "int64", "float32", "int32")],
        ),
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(summary) + 38, 800),
    )
