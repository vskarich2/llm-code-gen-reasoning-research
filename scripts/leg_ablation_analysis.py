#!/usr/bin/env python
"""LEG Ablation Analysis — produces metrics, tables, and plots from experiment outputs.

Reads:
  outputs/ablation_v2_alignment/summary.csv
  outputs/ablation_v2_alignment/regime_summary.csv
  outputs/ablation_v2_alignment/transition_matrix.csv
  logs/gpt-4o-mini-alignment-trial*_.jsonl (for attempt-level data)

Writes:
  outputs/analysis/*.csv
  outputs/analysis/*.png
"""

import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

BASE = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE / "outputs" / "ablation_v2_alignment"
OUTPUT_DIR = BASE / "outputs" / "analysis"
LOGS_DIR = BASE / "logs"


# ============================================================
# LOAD DATA
# ============================================================

def load_summary():
    """Load condition-level summary CSV."""
    return pd.read_csv(INPUT_DIR / "summary.csv")


def load_regime_summary():
    """Load regime × condition summary CSV."""
    return pd.read_csv(INPUT_DIR / "regime_summary.csv")


def load_transitions():
    """Load transition matrix CSV (long format)."""
    return pd.read_csv(INPUT_DIR / "transition_matrix.csv")


def load_attempt_level_data():
    """Load attempt-level data from raw JSONL logs for all trials."""
    rows = []
    for trial in [1, 2, 3]:
        pattern = str(LOGS_DIR / f"gpt-4o-mini-alignment-trial{trial}_*.jsonl")
        files = sorted(glob.glob(pattern))
        log_files = [f for f in files if "_prompts" not in f and "_responses" not in f]
        if not log_files:
            continue
        with open(log_files[0]) as f:
            for line in f:
                r = json.loads(line)
                if r.get("iteration") != "summary":
                    continue
                case_id = r.get("case_id")
                condition = r.get("condition")
                run_id = f"{case_id}__{condition}__t{trial}"
                converged = r.get("converged", False)
                regime = (r.get("trajectory_dynamics") or {}).get("pattern", "UNKNOWN")

                for e in r.get("trajectory", []):
                    rows.append({
                        "run_id": run_id,
                        "case_id": case_id,
                        "condition": condition,
                        "trial": trial,
                        "attempt_index": e.get("attempt", 0),
                        "success": e.get("pass", False),
                        "score": e.get("score", 0),
                        "leg_true": e.get("leg_true"),
                        "leg_coupling": e.get("leg_coupling"),
                        "leg_execution": e.get("leg_execution"),
                        "leg_keyword_only": e.get("leg_keyword_only", False),
                        "classifier_type": e.get("classifier_failure_type") or
                                           (e.get("classification") or {}).get("failure_type_final"),
                        "alignment_success": e.get("alignment_success"),
                        "alignment_score": e.get("alignment_step_coverage"),
                        "regime": regime,
                        "converged": converged,
                    })

    df = pd.DataFrame(rows)
    # Derive leg_subtype
    df["leg_subtype"] = None
    df.loc[df["leg_coupling"] == True, "leg_subtype"] = "coupling"
    df.loc[df["leg_execution"] == True, "leg_subtype"] = "execution"
    return df


# ============================================================
# STEP 1 — GLOBAL METRICS
# ============================================================

def compute_global_metrics(df):
    """Compute global and per-condition metrics from attempt-level data."""
    # Filter to evaluated attempts (leg_true is not None)
    evaluated = df[df["leg_true"].notna()].copy()

    total = len(evaluated)
    success_rate = evaluated["success"].mean()
    leg_rate = evaluated["leg_true"].mean()

    print("\n" + "=" * 60)
    print("STEP 1: GLOBAL METRICS")
    print("=" * 60)
    print(f"Total evaluated attempts: {total}")
    print(f"Success rate: {success_rate:.3f}")
    print(f"LEG_true rate (over evaluated): {leg_rate:.3f}")

    # Per condition
    per_cond = evaluated.groupby("condition").agg(
        attempts=("leg_true", "count"),
        success_rate=("success", "mean"),
        leg_rate=("leg_true", "mean"),
    ).round(3)
    print("\nPer-condition:")
    print(per_cond.to_string())

    per_cond.to_csv(OUTPUT_DIR / "global_metrics.csv")
    return evaluated


# ============================================================
# STEP 2 — FAILURE DECOMPOSITION
# ============================================================

def compute_failure_breakdown(df):
    """Decompose failures into LEG subtypes."""
    failures = df[(df["success"] == False) & (df["leg_true"].notna())].copy()
    n_fail = len(failures)

    if n_fail == 0:
        print("\nSTEP 2: No evaluated failures to decompose.")
        return

    leg_coupling = (failures["leg_subtype"] == "coupling").sum()
    leg_execution = (failures["leg_subtype"] == "execution").sum()
    leg_untyped = ((failures["leg_true"] == True) &
                   (failures["leg_subtype"].isna())).sum()
    non_leg = (failures["leg_true"] == False).sum()

    print("\n" + "=" * 60)
    print("STEP 2: FAILURE DECOMPOSITION")
    print("=" * 60)
    print(f"Total evaluated failures: {n_fail}")
    print(f"  LEG_coupling:    {leg_coupling:>4} ({leg_coupling/n_fail:.1%})")
    print(f"  LEG_execution:   {leg_execution:>4} ({leg_execution/n_fail:.1%})")
    print(f"  LEG_untyped:     {leg_untyped:>4} ({leg_untyped/n_fail:.1%})")
    print(f"  Non-LEG failure: {non_leg:>4} ({non_leg/n_fail:.1%})")

    breakdown = pd.DataFrame([{
        "category": "LEG_coupling", "count": leg_coupling, "pct": round(leg_coupling / n_fail, 3),
    }, {
        "category": "LEG_execution", "count": leg_execution, "pct": round(leg_execution / n_fail, 3),
    }, {
        "category": "LEG_untyped", "count": leg_untyped, "pct": round(leg_untyped / n_fail, 3),
    }, {
        "category": "Non_LEG_failure", "count": non_leg, "pct": round(non_leg / n_fail, 3),
    }])
    breakdown.to_csv(OUTPUT_DIR / "failure_breakdown.csv", index=False)

    # Per condition
    for cond in sorted(failures["condition"].unique()):
        cf = failures[failures["condition"] == cond]
        n = len(cf)
        leg = (cf["leg_true"] == True).sum()
        print(f"\n  {cond}: {leg}/{n} LEG_true ({leg/n:.1%})")


# ============================================================
# STEP 3 — LEG × REGIME
# ============================================================

def compute_regime_analysis(df):
    """LEG rates by trajectory regime."""
    evaluated = df[df["leg_true"].notna()].copy()

    if evaluated.empty:
        print("\nSTEP 3: No evaluated data for regime analysis.")
        return

    regime_stats = evaluated.groupby("regime").agg(
        total_attempts=("leg_true", "count"),
        leg_rate=("leg_true", "mean"),
        success_rate=("success", "mean"),
    ).round(3)

    # Add subtype rates
    for regime in regime_stats.index:
        mask = evaluated["regime"] == regime
        n = mask.sum()
        regime_stats.loc[regime, "coupling_rate"] = (
            (evaluated.loc[mask, "leg_subtype"] == "coupling").sum() / n if n else 0
        )
        regime_stats.loc[regime, "execution_rate"] = (
            (evaluated.loc[mask, "leg_subtype"] == "execution").sum() / n if n else 0
        )

    regime_stats = regime_stats.round(3)

    print("\n" + "=" * 60)
    print("STEP 3: LEG × REGIME")
    print("=" * 60)
    print(regime_stats.to_string())

    regime_stats.to_csv(OUTPUT_DIR / "leg_by_regime.csv")
    return regime_stats


def plot_regime_heatmap(regime_stats):
    """Heatmap: regime × LEG metrics."""
    if regime_stats is None or regime_stats.empty:
        return

    cols = ["leg_rate", "coupling_rate", "execution_rate"]
    available = [c for c in cols if c in regime_stats.columns]
    if not available:
        return

    data = regime_stats[available].astype(float)

    fig, ax = plt.subplots(figsize=(8, max(4, len(data) * 0.5 + 1)))
    sns.heatmap(data, annot=True, fmt=".3f", cmap="YlOrRd", ax=ax,
                linewidths=0.5, vmin=0, vmax=max(0.2, data.max().max()))
    ax.set_title("LEG Rates by Trajectory Regime")
    ax.set_ylabel("Regime")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fig_leg_regime_heatmap.png", dpi=150)
    plt.close()
    print("  Saved: fig_leg_regime_heatmap.png")


# ============================================================
# STEP 4 — CONDITION COMPARISON
# ============================================================

def compute_condition_comparison(df):
    """Compare conditions on LEG metrics."""
    evaluated = df[df["leg_true"].notna()].copy()

    if evaluated.empty:
        print("\nSTEP 4: No evaluated data for condition comparison.")
        return

    cond_stats = evaluated.groupby("condition").agg(
        attempts=("leg_true", "count"),
        success_rate=("success", "mean"),
        leg_rate=("leg_true", "mean"),
    ).round(3)

    for cond in cond_stats.index:
        mask = evaluated["condition"] == cond
        n = mask.sum()
        cond_stats.loc[cond, "coupling_rate"] = (
            (evaluated.loc[mask, "leg_subtype"] == "coupling").sum() / n if n else 0
        )
        cond_stats.loc[cond, "execution_rate"] = (
            (evaluated.loc[mask, "leg_subtype"] == "execution").sum() / n if n else 0
        )
    cond_stats = cond_stats.round(3)

    print("\n" + "=" * 60)
    print("STEP 4: CONDITION COMPARISON")
    print("=" * 60)
    print(cond_stats.to_string())

    cond_stats.to_csv(OUTPUT_DIR / "condition_comparison.csv")
    return cond_stats


def plot_condition_comparison(cond_stats):
    """Bar chart: LEG rates by condition."""
    if cond_stats is None or cond_stats.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(cond_stats))
    width = 0.25

    leg_vals = cond_stats["leg_rate"].values
    coup_vals = cond_stats.get("coupling_rate", pd.Series([0] * len(cond_stats))).values
    exec_vals = cond_stats.get("execution_rate", pd.Series([0] * len(cond_stats))).values

    ax.bar(x - width, leg_vals, width, label="LEG_true rate", color="#d62728")
    ax.bar(x, coup_vals, width, label="coupling_rate", color="#ff7f0e")
    ax.bar(x + width, exec_vals, width, label="execution_rate", color="#2ca02c")

    ax.set_xticks(x)
    ax.set_xticklabels(cond_stats.index, rotation=15)
    ax.set_ylabel("Rate")
    ax.set_title("LEG Rates by Condition")
    ax.legend()
    ax.set_ylim(0, max(0.15, max(leg_vals) * 1.3))
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fig_leg_by_condition.png", dpi=150)
    plt.close()
    print("  Saved: fig_leg_by_condition.png")


# ============================================================
# STEP 5 — TRANSITION ANALYSIS
# ============================================================

def compute_transitions(trans_df):
    """Analyze state transitions."""
    if trans_df is None or trans_df.empty:
        print("\nSTEP 5: No transition data.")
        return

    # Already in long format: from_state, to_state, count, probability
    print("\n" + "=" * 60)
    print("STEP 5: TRANSITION ANALYSIS")
    print("=" * 60)

    # Aggregate across conditions
    agg = trans_df.groupby(["from_state", "to_state"]).agg(
        total_count=("count", "sum")
    ).reset_index()

    # Compute probabilities
    row_totals = agg.groupby("from_state")["total_count"].transform("sum")
    agg["probability"] = (agg["total_count"] / row_totals).round(3)

    print("\nAggregated transition probabilities:")
    pivot = agg.pivot(index="from_state", columns="to_state", values="probability").fillna(0)
    print(pivot.round(3).to_string())

    # Key transitions
    print("\nKey transitions:")
    key_pairs = [
        ("LEG_COUPLING", "SUCCESS"),
        ("LEG_EXECUTION", "SUCCESS"),
        ("FAILURE_NO_LEG", "LEG_COUPLING"),
        ("FAILURE_NO_LEG", "LEG_TRUE_UNTYPED"),
        ("LEG_COUPLING", "LEG_COUPLING"),
        ("LEG_TRUE_UNTYPED", "LEG_TRUE_UNTYPED"),
        ("LEG_TRUE_UNTYPED", "SUCCESS"),
        ("FAILURE_NO_LEG", "SUCCESS"),
    ]
    for fs, ts in key_pairs:
        row = agg[(agg["from_state"] == fs) & (agg["to_state"] == ts)]
        if not row.empty:
            p = row.iloc[0]["probability"]
            c = row.iloc[0]["total_count"]
            print(f"  P({fs} → {ts}) = {p:.3f} (n={c})")
        else:
            print(f"  P({fs} → {ts}) = 0.000 (n=0)")

    # Per-condition
    for cond in sorted(trans_df["condition"].unique()):
        ct = trans_df[trans_df["condition"] == cond]
        print(f"\n  {cond}:")
        for _, row in ct.iterrows():
            print(f"    {row['from_state']:>20} → {row['to_state']:<20}: "
                  f"n={row['count']:>3}  P={row['probability']:.3f}")

    agg.to_csv(OUTPUT_DIR / "transition_probabilities.csv", index=False)
    return agg, pivot


def plot_transition_heatmap(pivot):
    """Transition probability heatmap."""
    if pivot is None or pivot.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(pivot, annot=True, fmt=".3f", cmap="Blues", ax=ax,
                linewidths=0.5, vmin=0, vmax=1.0)
    ax.set_title("State Transition Probabilities")
    ax.set_ylabel("From State")
    ax.set_xlabel("To State")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "fig_transition_matrix.png", dpi=150)
    plt.close()
    print("  Saved: fig_transition_matrix.png")


# ============================================================
# STEP 6 — PERSISTENCE
# ============================================================

def compute_persistence(df):
    """Compute LEG persistence per run."""
    if "run_id" not in df.columns:
        print("\nSTEP 6: No run_id for persistence analysis.")
        return

    evaluated = df[df["leg_true"].notna()].copy()
    runs = evaluated.groupby("run_id")

    persistence_rows = []
    for run_id, group in runs:
        group = group.sort_values("attempt_index")
        max_streak = 0
        current = 0
        for _, row in group.iterrows():
            if not row["success"] and row["leg_true"] == True:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        leg_count = ((~group["success"]) & (group["leg_true"] == True)).sum()
        persistence_rows.append({
            "run_id": run_id,
            "condition": group.iloc[0]["condition"],
            "regime": group.iloc[0]["regime"],
            "leg_true_count": leg_count,
            "max_leg_streak": max_streak,
            "attempts": len(group),
        })

    pers_df = pd.DataFrame(persistence_rows)

    # Only runs with at least one LEG event
    leg_runs = pers_df[pers_df["leg_true_count"] > 0]

    print("\n" + "=" * 60)
    print("STEP 6: LEG PERSISTENCE")
    print("=" * 60)
    print(f"Runs with LEG_true events: {len(leg_runs)}")
    if not leg_runs.empty:
        print(f"Mean LEG count per run (among LEG runs): {leg_runs['leg_true_count'].mean():.2f}")
        print(f"Mean max streak: {leg_runs['max_leg_streak'].mean():.2f}")
        print(f"Max streak overall: {leg_runs['max_leg_streak'].max()}")

        per_cond = leg_runs.groupby("condition").agg(
            runs=("run_id", "count"),
            mean_leg_count=("leg_true_count", "mean"),
            mean_max_streak=("max_leg_streak", "mean"),
            max_streak=("max_leg_streak", "max"),
        ).round(2)
        print("\nPer condition:")
        print(per_cond.to_string())

    pers_df.to_csv(OUTPUT_DIR / "leg_persistence.csv", index=False)


# ============================================================
# STEP 7 — KEY RESULTS SUMMARY
# ============================================================

def print_key_results(df, regime_stats, cond_stats, trans_agg):
    """Print final summary."""
    evaluated = df[df["leg_true"].notna()]

    print("\n" + "=" * 60)
    print("=== KEY RESULTS ===")
    print("=" * 60)

    # Overall LEG rate
    if not evaluated.empty:
        overall_leg = evaluated["leg_true"].mean()
        print(f"Overall LEG_true rate: {overall_leg:.3f} ({overall_leg:.1%})")
    else:
        print("Overall LEG_true rate: N/A (no evaluated data)")

    # Subtype split
    failures = evaluated[evaluated["success"] == False]
    if not failures.empty:
        leg_events = failures[failures["leg_true"] == True]
        coupling = (leg_events["leg_subtype"] == "coupling").sum()
        execution = (leg_events["leg_subtype"] == "execution").sum()
        untyped = leg_events["leg_subtype"].isna().sum()
        print(f"LEG subtype split: coupling={coupling}, execution={execution}, untyped={untyped}")

    # Highest LEG regime
    if regime_stats is not None and not regime_stats.empty:
        if "leg_rate" in regime_stats.columns:
            best = regime_stats["leg_rate"].idxmax()
            best_rate = regime_stats.loc[best, "leg_rate"]
            print(f"Highest LEG regime: {best} ({best_rate:.3f})")

    # Clustering
    if regime_stats is not None and "leg_rate" in regime_stats.columns:
        variance = regime_stats["leg_rate"].var()
        clusters = "YES" if variance > 0.001 else "NO"
        print(f"LEG clusters by regime? {clusters} (variance={variance:.4f})")

    # Condition comparison
    if cond_stats is not None and not cond_stats.empty:
        for cond in cond_stats.index:
            r = cond_stats.loc[cond, "leg_rate"]
            print(f"  {cond}: LEG_rate={r:.3f}")

    # Key transition
    if trans_agg is not None and not trans_agg.empty:
        leg_to_success = trans_agg[
            (trans_agg["from_state"].str.startswith("LEG")) &
            (trans_agg["to_state"] == "SUCCESS")
        ]
        if not leg_to_success.empty:
            total_count = leg_to_success["total_count"].sum()
            # Get total outgoing from LEG states
            leg_from = trans_agg[trans_agg["from_state"].str.startswith("LEG")]
            total_from = leg_from["total_count"].sum()
            p = total_count / total_from if total_from else 0
            print(f"P(LEG_* → SUCCESS) = {p:.3f} (n={total_count}/{total_from})")


# ============================================================
# MAIN
# ============================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Loading data...")

    # Load pre-computed summaries
    summary = load_summary()
    regime_summary = load_regime_summary()
    transitions = load_transitions()

    # Load attempt-level data from raw logs
    df = load_attempt_level_data()
    print(f"Loaded {len(df)} attempt-level records from {df['run_id'].nunique()} runs")
    print(f"Conditions: {sorted(df['condition'].unique())}")
    print(f"Evaluated attempts (leg_true not None): {df['leg_true'].notna().sum()}")

    # Run all analyses
    evaluated = compute_global_metrics(df)
    compute_failure_breakdown(df)
    regime_stats = compute_regime_analysis(df)
    cond_stats = compute_condition_comparison(df)

    # Transitions
    trans_agg = None
    pivot = None
    if transitions is not None and not transitions.empty:
        result = compute_transitions(transitions)
        if result:
            trans_agg, pivot = result

    # Persistence
    compute_persistence(df)

    # Plots
    print("\nGenerating plots...")
    plot_regime_heatmap(regime_stats)
    plot_condition_comparison(cond_stats)
    if pivot is not None:
        plot_transition_heatmap(pivot)

    # Key results
    print_key_results(df, regime_stats, cond_stats, trans_agg)

    # List outputs
    print("\n" + "=" * 60)
    print("OUTPUT FILES")
    print("=" * 60)
    for f in sorted(os.listdir(OUTPUT_DIR)):
        size = os.path.getsize(OUTPUT_DIR / f)
        print(f"  {f}: {size} bytes")


if __name__ == "__main__":
    main()
