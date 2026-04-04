"""Metric card rendering and formatting."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.compute_engine import compute_metrics

PRIMARY_METRICS = {
    "pass_rate": {"label": "Pass Rate", "fmt": "{:.1%}"},
    "leg_rate": {"label": "LEG Rate", "fmt": "{:.1%}"},
    "lucky_fix_rate": {"label": "Lucky Fix Rate", "fmt": "{:.1%}"},
    "reasoning_rate": {"label": "Reasoning Rate", "fmt": "{:.1%}"},
    "count": {"label": "Attempts", "fmt": "{:,.0f}"},
}


def format_metric_value(metric: str, value: Any) -> str:
    spec = PRIMARY_METRICS.get(metric, {})
    fmt = spec.get("fmt")
    if fmt is None:
        return str(value)
    try:
        return fmt.format(value)
    except Exception:
        return str(value)


def render_metric_cards(df: pd.DataFrame) -> None:
    metrics_to_render = ["pass_rate", "leg_rate", "lucky_fix_rate", "reasoning_rate", "count"]
    result = compute_metrics(df, metrics_to_render, [])
    if result.empty:
        st.info("No metrics available.")
        return
    row = result.iloc[0]
    cols = st.columns(len(metrics_to_render))
    for col, metric in zip(cols, metrics_to_render):
        label = PRIMARY_METRICS[metric]["label"]
        value = row.get(metric, 0)
        col.metric(label, format_metric_value(metric, value))
