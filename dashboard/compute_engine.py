"""Generic aggregation engine — computes any registered metric over any grouping.

No domain-specific logic. Resolves metrics from metrics_registry.py.
"""

from __future__ import annotations

import pandas as pd

from dashboard.metrics_registry import METRICS


def compute_metrics(
    df: pd.DataFrame,
    metric_names: list[str],
    groupby: list[str],
) -> pd.DataFrame:
    """Compute named metrics grouped by specified columns.

    Args:
        df: attempt-level DataFrame with derived fields applied.
        metric_names: list of metric names from METRICS registry.
        groupby: columns to group by (e.g., ["model", "condition"]).

    Returns:
        DataFrame with groupby columns as index, one column per metric.

    Raises:
        KeyError: if any metric_name is not in registry.
        KeyError: if any groupby column is not in df.
    """
    # Validate
    for name in metric_names:
        if name not in METRICS:
            raise KeyError(
                f"Unknown metric '{name}'. "
                f"Available: {sorted(METRICS.keys())}"
            )
    for col in groupby:
        if col not in df.columns:
            raise KeyError(
                f"Groupby column '{col}' not in DataFrame. "
                f"Available: {sorted(df.columns.tolist())}"
            )

    if not groupby:
        # Global aggregation (no grouping)
        result = {}
        for name in metric_names:
            result[name] = METRICS[name]["compute"](df)
        return pd.DataFrame([result])

    grouped = df.groupby(groupby, sort=True)
    result_rows = []

    for group_key, group_df in grouped:
        if isinstance(group_key, tuple):
            row = dict(zip(groupby, group_key))
        else:
            row = {groupby[0]: group_key}

        for name in metric_names:
            row[name] = METRICS[name]["compute"](group_df)

        result_rows.append(row)

    return pd.DataFrame(result_rows)


def compute_single_metric(
    df: pd.DataFrame,
    metric_name: str,
) -> float | dict:
    """Compute a single metric over the entire DataFrame (no grouping)."""
    if metric_name not in METRICS:
        raise KeyError(f"Unknown metric '{metric_name}'")
    return METRICS[metric_name]["compute"](df)


def list_metrics() -> dict[str, str]:
    """Return {name: description} for all registered metrics."""
    return {
        name: spec["description"]
        for name, spec in METRICS.items()
    }
