"""DataFrame styling utilities."""

from __future__ import annotations

from typing import Any

import pandas as pd


def style_dataframe(df: pd.DataFrame, metric_columns: list[str] | None = None) -> pd.io.formats.style.Styler:
    metric_columns = metric_columns or []
    fmt: dict[str, str] = {}
    for column in metric_columns:
        if column in ("count", "trial_idx", "attempt_idx"):
            fmt[column] = "{:,.0f}"
        else:
            fmt[column] = "{:.3f}"
    styler = df.style.format(fmt)
    gradient_cols = [c for c in metric_columns if c in df.columns and c not in {"count"}]
    if gradient_cols:
        styler = styler.background_gradient(subset=gradient_cols, cmap="Blues")
    return styler


def _cell_map(s: pd.io.formats.style.Styler, func: Any, **kwargs: Any) -> pd.io.formats.style.Styler:
    """Compat: pandas >=2.1 uses .map(), older uses .applymap()."""
    return s.map(func, **kwargs) if hasattr(s, "map") else s.applymap(func, **kwargs)


def style_field_introspection_table(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    def color_null_pct(val: Any) -> str:
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        if v > 50:
            return "background-color: #c62828; color: white; font-weight: 700;"
        if v > 20:
            return "background-color: rgba(198,40,40,0.35);"
        if v > 10:
            return "background-color: rgba(198,40,40,0.18);"
        return ""

    def color_unique(val: Any) -> str:
        try:
            v = int(val)
        except (TypeError, ValueError):
            return ""
        if v == 1:
            return "color: #9e9e9e; font-style: italic;"
        if v > 100:
            return "background-color: #bbdefb;"
        if v > 10:
            return "background-color: #e3f2fd;"
        return ""

    def color_dtype(val: Any) -> str:
        s = str(val)
        if "str" in s or s == "object":
            return "background-color: #e8f5e9;"
        if "int" in s or "float" in s:
            return "background-color: #e3f2fd;"
        return "background-color: #f5f5f5;"

    def color_source(val: Any) -> str:
        s = str(val)
        if s == "derived":
            return "background-color: #fff9c4;"
        if s.startswith("payload"):
            return "background-color: #f3e5f5;"
        return "background-color: #fafafa;"

    styler = df.style
    styler = _cell_map(styler, color_null_pct, subset=["null_%"])
    styler = _cell_map(styler, color_unique, subset=["unique"])
    styler = _cell_map(styler, color_dtype, subset=["dtype"])
    styler = _cell_map(styler, color_source, subset=["source"])
    return (
        styler
        .set_properties(subset=["column", "sample"], **{"font-family": "monospace"})
        .set_properties(**{"font-size": "13px", "padding": "6px 10px"})
        .set_table_styles(
            [
                {"selector": "thead th", "props": [("background-color", "#263238"), ("color", "white"), ("font-weight", "bold")]},
                {"selector": "tbody tr:nth-child(even)", "props": [("background-color", "#fafafa")]},
                {"selector": "tbody tr:hover", "props": [("background-color", "#e8eaf6")]},
            ]
        )
    )
