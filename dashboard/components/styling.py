"""DataFrame styling utilities."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _is_integer_column(df: pd.DataFrame, col: str) -> bool:
    """Check if a column contains only integer values (no fractional part)."""
    if col not in df.columns:
        return False
    s = df[col].dropna()
    if len(s) == 0:
        return False
    if s.dtype in ("int64", "int32", "Int64", "Int32"):
        return True
    if s.dtype in ("float64", "float32"):
        return (s == s.astype(int)).all()
    return False


_KNOWN_COUNT_NAMES = frozenset({
    "count", "n", "N", "trial_idx", "attempt_idx",
    "CORRECT", "PARTIAL", "WRONG", "INCORRECT", "UNJUDGABLE",
    "tests_passed", "tests_total",
})


def style_dataframe(df: pd.DataFrame, metric_columns: list[str] | None = None) -> pd.io.formats.style.Styler:
    metric_columns = metric_columns or []
    fmt: dict[str, str] = {}
    for column in metric_columns:
        if column in _KNOWN_COUNT_NAMES or _is_integer_column(df, column):
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
            return "background-color: #c62828; color: white; font-weight: bold;"
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
        return ""

    styler = df.style
    styler = _cell_map(styler, color_null_pct, subset=["null_%"])
    styler = _cell_map(styler, color_unique, subset=["unique"])
    return (
        styler
        .set_properties(subset=["column", "sample"], **{"font-family": "monospace"})
        .set_properties(**{"font-size": "13px", "padding": "6px 10px"})
    )
