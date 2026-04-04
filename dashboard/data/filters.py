"""Global filter construction and application."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def build_global_filters(df: pd.DataFrame) -> dict[str, list[str]]:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Global Filters**")

    filters: dict[str, list[str]] = {}
    for field, label in [
        ("model", "Model"),
        ("condition", "Condition"),
        ("family", "Family"),
        ("difficulty", "Difficulty"),
    ]:
        if field not in df.columns:
            continue
        values = sorted([v for v in df[field].dropna().unique().tolist() if v != ""])
        selected = st.sidebar.multiselect(label, values, default=values, key=f"flt_{field}")
        filters[field] = selected
    return filters


def apply_filters(df: pd.DataFrame, filters: dict[str, list[str]]) -> pd.DataFrame:
    out = df.copy()
    for field, selected in filters.items():
        if field in out.columns and selected:
            out = out[out[field].isin(selected)]
    return out
