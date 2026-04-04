"""Run sig_stats analysis on V2.1 ablation logs.

Loads events.jsonl from both ablation runs, builds the dataframe
sig_stats.py expects, then runs the full analysis pipeline:
HTE, permutation tests, mixed-effects models, and delta summaries.

Usage:
    .venv/bin/python scripts/run_sig_stats.py
    .venv/bin/python scripts/run_sig_stats.py --logs logs/v21_validation logs/v21_5mini_ablation
"""

import argparse
import json
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# =========================
# CONFIG
# =========================

BASELINE = "baseline_v2"
TREATMENT = "leg_reduction_v2"
TREATMENT_LEAN = "leg_reduction_lean_v2"

DELTA_THRESHOLD = 0.0
N_PERM = 2000
RANDOM_SEED = 42

DEFAULT_LOG_DIRS = [
    "logs/v21_validation",
    "logs/v21_5mini_ablation",
]


# =========================
# DATA LOADING
# =========================

def load_events(log_dirs):
    """Load all case.end events from ablation logs into rows."""
    rows = []
    for log_dir in log_dirs:
        for f in sorted(glob.glob(
                f"{log_dir}/**/events.jsonl", recursive=True)):
            with open(f) as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("event_type") != "case.end":
                        continue
                    p = ev.get("payload", {})
                    rows.append({
                        "case_id": ev.get("case_id"),
                        "model": ev.get("model"),
                        "trial_idx": ev.get("trial"),
                        "condition": ev.get("condition"),
                        "pass": int(p.get("pass", False)),
                        "score": p.get("score", 0.0),
                        "mechanism_correct": p.get(
                            "mechanism_correct"),
                        "reasoning_correct": p.get(
                            "reasoning_correct_compat"),
                        "category": p.get("v2_category",
                                          p.get("category", "")),
                        "execution_category": p.get(
                            "execution_category", ""),
                    })
    return pd.DataFrame(rows)


def derive_columns(df):
    """Add derived columns for sig_stats compatibility."""
    df["leg_true"] = (
        (df["mechanism_correct"] == True)
        & (df["pass"] == 0)
    ).astype(int)

    df["lucky_fix"] = (
        (df["pass"] == 1)
        & (df["mechanism_correct"] == False)
    ).astype(int)

    return df


# =========================
# ANALYSIS (from sig_stats.py, adapted)
# =========================

def compute_delta(agg, metric_name, baseline, treatment):
    pivot = agg.pivot_table(
        index=["case_id", "model"],
        columns="condition",
        values=metric_name,
    )
    if baseline not in pivot.columns:
        raise ValueError(f"Missing {baseline} in conditions")
    if treatment not in pivot.columns:
        raise ValueError(f"Missing {treatment} in conditions")
    pivot = pivot.copy()
    pivot["delta"] = pivot[treatment] - pivot[baseline]
    return pivot.reset_index()


def classify_delta(df_delta):
    df_delta = df_delta.copy()
    df_delta["effect"] = df_delta["delta"].apply(
        lambda d: "help" if d > DELTA_THRESHOLD
        else ("hurt" if d < -DELTA_THRESHOLD else "neutral")
    )
    return df_delta


def compute_hte(df_delta):
    results = []
    for case_id, group in df_delta.groupby("case_id"):
        effects = set(group["effect"])
        results.append({
            "case_id": case_id,
            "has_help": "help" in effects,
            "has_hurt": "hurt" in effects,
            "HTE": int("help" in effects and "hurt" in effects),
        })
    hte_df = pd.DataFrame(results)
    return hte_df, hte_df["HTE"].mean()


def permutation_test(df, metric_col, baseline, treatment):
    rng = np.random.default_rng(RANDOM_SEED)

    # Filter to only baseline and treatment
    df_bt = df[df["condition"].isin([baseline, treatment])].copy()

    # Observed
    agg_obs = (
        df_bt.groupby(["case_id", "model", "condition"])
        .agg(val=(metric_col, "mean"))
        .reset_index()
    )
    obs_delta = compute_delta(agg_obs, "val", baseline, treatment)
    obs_delta = classify_delta(obs_delta)
    _, observed_hte_rate = compute_hte(obs_delta)

    perm_rates = []
    cond_values = list(df_bt["condition"].values)
    for _ in range(N_PERM):
        shuffled_conds = list(cond_values)
        rng.shuffle(shuffled_conds)
        df_shuffled = df_bt.copy()
        df_shuffled["condition"] = shuffled_conds

        agg_s = (
            df_shuffled
            .groupby(["case_id", "model", "condition"])
            .agg(val=(metric_col, "mean"))
            .reset_index()
        )
        pivot = agg_s.pivot_table(
            index=["case_id", "model"],
            columns="condition", values="val",
        )
        if baseline not in pivot.columns:
            continue
        if treatment not in pivot.columns:
            continue
        pivot["delta"] = pivot[treatment] - pivot[baseline]
        pivot = pivot.reset_index()
        pivot = classify_delta(pivot)
        _, perm_rate = compute_hte(pivot)
        perm_rates.append(perm_rate)

    perm_rates = np.array(perm_rates)
    p_value = np.mean(perm_rates >= observed_hte_rate)
    return observed_hte_rate, p_value


def run_mixed_effects(df, outcome, baseline, treatment):
    df_bt = df[df["condition"].isin([baseline, treatment])].copy()
    df_bt["is_treatment"] = (
        df_bt["condition"] == treatment).astype(int)

    # Rename column if it's a Python reserved word
    col = outcome
    if outcome == "pass":
        df_bt = df_bt.rename(columns={"pass": "pass_outcome"})
        col = "pass_outcome"

    try:
        model = smf.mixedlm(
            f"{col} ~ is_treatment * model",
            data=df_bt,
            groups=df_bt["case_id"],
            re_formula="~1",
        ).fit(reml=False)
        return model
    except Exception as e:
        print(f"  Mixed effects failed: {e}")
        return None


def summarize_delta(df_delta, metric_name):
    summary = (
        df_delta.groupby("model")["delta"]
        .agg(["mean", "std", "count"])
        .reset_index()
    )
    summary["metric"] = metric_name
    return summary


# =========================
# MAIN
# =========================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", nargs="+", default=DEFAULT_LOG_DIRS)
    args = parser.parse_args()

    print(f"Loading events from: {args.logs}")
    df = load_events(args.logs)
    df = derive_columns(df)

    print(f"Total rows: {len(df)}")
    print(f"Models: {sorted(df['model'].unique())}")
    print(f"Conditions: {sorted(df['condition'].unique())}")
    print(f"Cases: {df['case_id'].nunique()}")
    print(f"Trials: {sorted(df['trial_idx'].unique())}")
    print()

    # Aggregate to case x model x condition
    agg = (
        df.groupby(["case_id", "model", "condition"])
        .agg(
            pass_rate=("pass", "mean"),
            leg_rate=("leg_true", "mean"),
            score_mean=("score", "mean"),
        )
        .reset_index()
    )

    # Run for each treatment condition
    for treatment_name, treatment_cond in [
        ("LEG", TREATMENT),
        ("LEG_LEAN", TREATMENT_LEAN),
    ]:
        # Check if this treatment exists in case_data
        if treatment_cond not in df["condition"].unique():
            print(f"\n=== Skipping {treatment_name} "
                  f"(not in data) ===")
            continue

        print(f"\n{'='*70}")
        print(f"ANALYSIS: {BASELINE} vs {treatment_cond}")
        print(f"{'='*70}")

        # Deltas
        try:
            dp = compute_delta(
                agg, "pass_rate", BASELINE, treatment_cond)
            dp = classify_delta(dp)
            dl = compute_delta(
                agg, "leg_rate", BASELINE, treatment_cond)
            dl = classify_delta(dl)
            ds = compute_delta(
                agg, "score_mean", BASELINE, treatment_cond)
            ds = classify_delta(ds)
        except ValueError as e:
            print(f"  Skipped: {e}")
            continue

        # HTE
        hte_pass_df, hte_pass_rate = compute_hte(dp)
        hte_leg_df, hte_leg_rate = compute_hte(dl)

        print(f"\n  HTE rate (pass):  {hte_pass_rate:.3f}")
        print(f"  HTE rate (LEG):   {hte_leg_rate:.3f}")

        # Permutation tests
        print(f"\n  Permutation test (pass)...")
        obs_p, pval_p = permutation_test(
            df, "pass", BASELINE, treatment_cond)
        print(f"    Observed HTE: {obs_p:.3f}, "
              f"p-value: {pval_p:.4f}")

        print(f"  Permutation test (LEG)...")
        obs_l, pval_l = permutation_test(
            df, "leg_true", BASELINE, treatment_cond)
        print(f"    Observed HTE: {obs_l:.3f}, "
              f"p-value: {pval_l:.4f}")

        # Mixed effects
        print(f"\n  Mixed effects model (pass):")
        me_pass = run_mixed_effects(
            df, "pass", BASELINE, treatment_cond)
        if me_pass:
            print(me_pass.summary())

        print(f"\n  Mixed effects model (LEG):")
        me_leg = run_mixed_effects(
            df, "leg_true", BASELINE, treatment_cond)
        if me_leg:
            print(me_leg.summary())

        # Delta summary
        sp = summarize_delta(dp, "pass")
        sl = summarize_delta(dl, "leg")
        ss = summarize_delta(ds, "score")
        summary = pd.concat([sp, sl, ss], ignore_index=True)

        print(f"\n  Delta summary "
              f"({treatment_name} - baseline):")
        print(summary.to_string(index=False))

        # Per-case breakdown: which cases does LEG help/hurt?
        print(f"\n  Cases where {treatment_name} HELPS "
              f"(>10pp gain, any model):")
        for _, row in dp.iterrows():
            if row["delta"] > 0.1:
                print(f"    {row['case_id']:35s} "
                      f"{row['model']:20s} "
                      f"+{row['delta']:.0%}")

        print(f"\n  Cases where {treatment_name} HURTS "
              f"(>10pp loss, any model):")
        for _, row in dp.iterrows():
            if row["delta"] < -0.1:
                print(f"    {row['case_id']:35s} "
                      f"{row['model']:20s} "
                      f"{row['delta']:.0%}")


if __name__ == "__main__":
    main()
