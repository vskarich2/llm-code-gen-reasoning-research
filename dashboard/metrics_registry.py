"""Metric registry — ALL metrics defined here and ONLY here.

Adding a new metric = adding one entry to METRICS. No other file changes.

Each metric has:
  - compute: function(df_group) → scalar
  - description: human-readable label
"""

import numpy as np


def _pass_rate(df):
    return df["exec_pass"].mean()


def _leg_rate(df):
    col = df["is_leg"]
    return col.dropna().mean() if col.notna().any() else np.nan


def _lucky_fix_rate(df):
    col = df["is_lucky_fix"]
    return col.dropna().mean() if col.notna().any() else np.nan


def _reasoning_rate(df):
    col = df["reasoning_correct"]
    return col.dropna().mean() if col.notna().any() else np.nan


def _recon_pass_rate(df):
    return df["recon_pass"].mean()


def _count(df):
    return len(df)


def _mean_score(df):
    col = df["score"]
    return col.dropna().mean() if col.notna().any() else np.nan


def _retry_recovery_rate(df):
    """Fraction of chains where first attempt fails but final passes."""
    chains = df.groupby("chain_id")
    recovered = 0
    eligible = 0
    for _, g in chains:
        g = g.sort_values("attempt_idx")
        if len(g) < 2:
            continue
        first_pass = g.iloc[0]["exec_pass"]
        final_pass = g.iloc[-1]["exec_pass"]
        if not first_pass:
            eligible += 1
            if final_pass:
                recovered += 1
    return recovered / eligible if eligible > 0 else np.nan


def _avg_attempts(df):
    """Average number of attempts per chain."""
    if "n_attempts" in df.columns:
        # Use precomputed n_attempts (one value per chain)
        return df.groupby("chain_id")["attempt_idx"].max().mean() + 1
    return 1.0


def _pct_improved_by_retry(df):
    """% of multi-attempt chains where final score > first score."""
    chains = df.groupby("chain_id")
    improved = 0
    total = 0
    for _, g in chains:
        g = g.sort_values("attempt_idx")
        if len(g) < 2:
            continue
        total += 1
        if g.iloc[-1]["exec_pass"] and not g.iloc[0]["exec_pass"]:
            improved += 1
    return improved / total if total > 0 else np.nan


def _pct_degraded_by_retry(df):
    """% of multi-attempt chains where first passes but final fails."""
    chains = df.groupby("chain_id")
    degraded = 0
    total = 0
    for _, g in chains:
        g = g.sort_values("attempt_idx")
        if len(g) < 2:
            continue
        total += 1
        if g.iloc[0]["exec_pass"] and not g.iloc[-1]["exec_pass"]:
            degraded += 1
    return degraded / total if total > 0 else np.nan


def _trajectory_distribution(df):
    """Distribution of trajectory types. Returns dict."""
    if "trajectory_type" not in df.columns:
        return {}
    # One trajectory_type per chain — deduplicate
    chain_types = df.groupby("chain_id")["trajectory_type"].first()
    return chain_types.value_counts().to_dict()


# ═══════════════════════════════════════════════════════════════
# THE REGISTRY
# ═══════════════════════════════════════════════════════════════
# Adding a metric = adding one entry here. Nothing else changes.

METRICS = {
    "pass_rate": {
        "compute": _pass_rate,
        "description": "Fraction of attempts where code passes tests",
    },
    "leg_rate": {
        "compute": _leg_rate,
        "description": "Fraction with correct reasoning but failing code",
    },
    "lucky_fix_rate": {
        "compute": _lucky_fix_rate,
        "description": "Fraction with wrong reasoning but passing code",
    },
    "reasoning_rate": {
        "compute": _reasoning_rate,
        "description": "Fraction with correct reasoning",
    },
    "recon_pass_rate": {
        "compute": _recon_pass_rate,
        "description": "Pass rate conditioned on successful reconstruction",
    },
    "count": {
        "compute": _count,
        "description": "Number of attempts",
    },
    "mean_score": {
        "compute": _mean_score,
        "description": "Average execution score",
    },
    "retry_recovery_rate": {
        "compute": _retry_recovery_rate,
        "description": "% of failed-first-attempt chains that eventually pass",
    },
    "avg_attempts": {
        "compute": _avg_attempts,
        "description": "Average attempts per chain",
    },
    "pct_improved": {
        "compute": _pct_improved_by_retry,
        "description": "% of retry chains that improved (fail→pass)",
    },
    "pct_degraded": {
        "compute": _pct_degraded_by_retry,
        "description": "% of retry chains that degraded (pass→fail)",
    },
    "trajectory_distribution": {
        "compute": _trajectory_distribution,
        "description": "Distribution of retry trajectory types",
    },
}
