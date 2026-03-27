#!/usr/bin/env python
"""Paper-grade analysis for LEG ablation experiments.

Reads validated events_merged.jsonl and produces:
  - 5 figures (PNG)
  - 3 tables (CSV)
  - stats_summary.json
  - paper_results_summary.txt

REQUIRES: merge_and_validate.py must pass first.

Usage:
    .venv/bin/python scripts/paper_analysis.py \
        --input logs/events_merged.jsonl \
        --output-dir logs/paper_outputs
"""

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats as sp_stats
from statsmodels.formula.api import ols
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SEED = 42
BOOTSTRAP_SAMPLES = 1000


# ============================================================
# DATA LOADING + GATING
# ============================================================


def load_and_gate(input_path: Path) -> list[dict]:
    """Single-pass load with hard gating. Returns event list.

    ASSUMPTION: merge_and_validate has ensured completeness and correctness.
    """
    if not input_path.exists():
        print(f"ERROR: {input_path} not found. Run merge_and_validate.py first.")
        sys.exit(1)

    # Single-pass read
    with open(input_path, "r", encoding="utf-8") as f:
        lines = [line for line in f if line.strip()]

    if not lines:
        print("ERROR: events_merged.jsonl is empty.")
        sys.exit(1)

    # Validate first line
    try:
        json.loads(lines[0])
    except (json.JSONDecodeError, ValueError):
        print("ERROR: events_merged.jsonl is malformed. Re-run merge_and_validate.py.")
        sys.exit(1)

    events = [json.loads(line) for line in lines]

    # Verify completeness
    models = set(e["model"] for e in events)
    conditions = set(e["condition"] for e in events)
    trials = set(e["trial"] for e in events)
    cases = set(e["case_id"] for e in events)
    expected = len(models) * len(conditions) * len(trials) * len(cases)
    if len(events) != expected:
        print(
            f"ERROR: Expected {expected} events, found {len(events)}. "
            "Data is incomplete or corrupt. Re-run merge_and_validate.py."
        )
        sys.exit(1)

    return events


# ============================================================
# CASE-LEVEL AGGREGATION
# ============================================================


def build_case_level_df(events: list[dict]) -> pd.DataFrame:
    """Aggregate events to case-level: mean across trials per (model, case_id, condition).

    Sort by case_id for deterministic ordering before any aggregation.
    """
    df = pd.DataFrame(events)

    # Derive boolean columns
    df["is_pass"] = df["pass"].astype(bool)
    df["reasoning_correct_bool"] = df["reasoning_correct"].fillna(False).astype(bool)
    df["code_correct_bool"] = df["code_correct"].fillna(False).astype(bool)

    # LEG: reasoning_correct AND NOT code_correct
    df["is_leg"] = df["reasoning_correct_bool"] & ~df["code_correct_bool"]
    # Lucky fix: NOT reasoning_correct AND code_correct
    df["is_lucky"] = ~df["reasoning_correct_bool"] & df["code_correct_bool"]

    # Sort by case_id for deterministic ordering
    df = df.sort_values("case_id")

    # Aggregate per (model, case_id, condition) — mean across trials
    case_df = (
        df.groupby(["model", "case_id", "condition"])
        .agg(
            pass_rate=("is_pass", "mean"),
            leg_rate=("is_leg", "mean"),
            lucky_fix_rate=("is_lucky", "mean"),
            n_trials=("trial", "nunique"),
        )
        .reset_index()
    )

    case_df = case_df.sort_values("case_id")
    return case_df


def compute_exec_reasoning(events: list[dict], model: str, condition: str) -> float:
    """P(code_correct | reasoning_correct) for a model+condition subset.

    Denominator: ONLY rows where reasoning_correct == True.
    """
    subset = [
        e
        for e in events
        if e["model"] == model
        and e["condition"] == condition
        and e.get("reasoning_correct") is True
    ]
    if not subset:
        return float("nan")
    return sum(1 for e in subset if e.get("code_correct") is True) / len(subset)


# ============================================================
# PAIRED T-TEST (with alignment + zero-variance handling)
# ============================================================


def paired_ttest(case_df: pd.DataFrame, model: str, metric: str = "pass_rate"):
    """Paired t-test: baseline vs leg_reduction for one model.

    Returns dict with t_stat, p_value, mean_diff, note.
    Raises ValueError if case alignment fails.
    """
    bl = case_df[(case_df["model"] == model) & (case_df["condition"] == "baseline")].sort_values(
        "case_id"
    )
    lr = case_df[
        (case_df["model"] == model) & (case_df["condition"] == "leg_reduction")
    ].sort_values("case_id")

    # Strict alignment check — no silent reordering
    bl_cases = list(bl["case_id"])
    lr_cases = list(lr["case_id"])
    if bl_cases != lr_cases:
        raise ValueError(
            f"Case alignment mismatch for model {model}: "
            f"baseline has {len(bl_cases)} cases, leg_reduction has {len(lr_cases)} cases. "
            f"Difference: {set(bl_cases) ^ set(lr_cases)}"
        )

    bl_vals = bl[metric].values.astype(float)
    lr_vals = lr[metric].values.astype(float)

    # Check for NaN/inf
    if np.any(np.isnan(bl_vals)) or np.any(np.isnan(lr_vals)):
        raise ValueError(f"NaN values in {metric} for model {model}")
    if np.any(np.isinf(bl_vals)) or np.any(np.isinf(lr_vals)):
        raise ValueError(f"Inf values in {metric} for model {model}")

    diffs = lr_vals - bl_vals
    mean_diff = float(np.mean(diffs))

    # Zero-variance handling — do NOT call scipy (inconsistent across versions)
    # Use tolerance for floating-point comparison
    if len(diffs) == 0:
        raise ValueError(f"Empty paired vectors for model {model}")
    if np.var(diffs) < 1e-15:
        return {
            "t_stat": float("inf") if mean_diff != 0 else 0.0,
            "p_value": 0.0 if mean_diff != 0 else 1.0,
            "mean_diff": mean_diff,
            "note": "zero variance (constant difference)",
        }

    t_stat, p_value = sp_stats.ttest_rel(lr_vals, bl_vals)
    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "mean_diff": mean_diff,
        "note": None,
    }


# ============================================================
# BOOTSTRAP CI (pairing-preserving)
# ============================================================


def bootstrap_ci(
    case_df: pd.DataFrame,
    model: str,
    metric: str,
    rng: np.random.Generator,
    n_boot: int = BOOTSTRAP_SAMPLES,
):
    """Bootstrap 95% CI for paired difference (leg_reduction - baseline).

    Preserves pairing by resampling case indices.
    """
    bl = case_df[(case_df["model"] == model) & (case_df["condition"] == "baseline")].sort_values(
        "case_id"
    )
    lr = case_df[
        (case_df["model"] == model) & (case_df["condition"] == "leg_reduction")
    ].sort_values("case_id")

    assert list(bl["case_id"]) == list(lr["case_id"]), "Case alignment mismatch in bootstrap"

    bl_vals = bl[metric].values.astype(float)
    lr_vals = lr[metric].values.astype(float)

    if np.any(np.isnan(bl_vals)) or np.any(np.isnan(lr_vals)):
        raise ValueError(f"NaN in bootstrap input for {model}/{metric}")

    n = len(bl_vals)
    diffs = lr_vals - bl_vals

    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        indices = rng.integers(0, n, size=n)
        boot_means[i] = np.mean(diffs[indices])

    ci_low = float(np.percentile(boot_means, 2.5))
    ci_high = float(np.percentile(boot_means, 97.5))
    mean_diff = float(np.mean(diffs))

    return {
        "ci_low": ci_low,
        "ci_high": ci_high,
        "mean_diff": mean_diff,
        "boot_mean": float(np.mean(boot_means)),
        "boot_std": float(np.std(boot_means)),
    }


# ============================================================
# INTERACTION ANALYSIS
# ============================================================


def interaction_ols(case_df: pd.DataFrame, metric: str = "pass_rate"):
    """OLS interaction model: metric ~ C(model) * C(condition)."""
    formula = f"{metric} ~ C(model) * C(condition)"
    model = ols(formula, data=case_df).fit()
    return {
        "params": {k: float(v) for k, v in model.params.items()},
        "pvalues": {k: float(v) for k, v in model.pvalues.items()},
        "rsquared": float(model.rsquared),
    }


def bootstrap_dod(
    case_df: pd.DataFrame,
    model_a: str,
    model_b: str,
    metric: str,
    rng: np.random.Generator,
    n_boot: int = BOOTSTRAP_SAMPLES,
):
    """Bootstrap difference-of-differences: (B_lr - B_bl) - (A_lr - A_bl)."""

    def _get_diffs(model):
        bl = case_df[
            (case_df["model"] == model) & (case_df["condition"] == "baseline")
        ].sort_values("case_id")
        lr = case_df[
            (case_df["model"] == model) & (case_df["condition"] == "leg_reduction")
        ].sort_values("case_id")
        assert list(bl["case_id"]) == list(lr["case_id"])
        return lr[metric].values - bl[metric].values

    diffs_a = _get_diffs(model_a)
    diffs_b = _get_diffs(model_b)

    # Align by case
    n = min(len(diffs_a), len(diffs_b))
    dod = diffs_b[:n] - diffs_a[:n]

    boot_dod = np.empty(n_boot)
    for i in range(n_boot):
        indices = rng.integers(0, n, size=n)
        boot_dod[i] = np.mean(dod[indices])

    return {
        "ci_low": float(np.percentile(boot_dod, 2.5)),
        "ci_high": float(np.percentile(boot_dod, 97.5)),
        "mean_dod": float(np.mean(dod)),
        "boot_mean": float(np.mean(boot_dod)),
    }


# ============================================================
# VALIDATION CROSS-CHECKS
# ============================================================


def validate_stats(case_df: pd.DataFrame, events: list[dict]):
    """Cross-check computed statistics. Raises on any mismatch."""
    # numpy vs pandas mean
    for model in case_df["model"].unique():
        for cond in case_df["condition"].unique():
            subset = case_df[(case_df["model"] == model) & (case_df["condition"] == cond)]
            vals = subset["pass_rate"].values
            np_mean = float(np.mean(vals))
            pd_mean = float(pd.Series(vals).mean())
            if abs(np_mean - pd_mean) > 1e-10:
                raise RuntimeError(
                    f"Statistical validation failed: numpy/pandas mean mismatch "
                    f"for {model}/{cond}: {np_mean} vs {pd_mean}"
                )

    # Check no NaN in case_df
    for col in ["pass_rate", "leg_rate", "lucky_fix_rate"]:
        if case_df[col].isna().any():
            raise RuntimeError(f"NaN detected in case_df column '{col}'")


# ============================================================
# FIGURES
# ============================================================


def figure_1_model_condition_panel(case_df, events, output_dir, rng):
    """Model × Condition panel: pass, LEG, lucky fix, Exec|Reasoning with 95% CI."""
    models = sorted(case_df["model"].unique())
    conditions = sorted(case_df["condition"].unique())
    metrics = ["pass_rate", "leg_rate", "lucky_fix_rate"]

    fig, axes = plt.subplots(1, len(metrics) + 1, figsize=(16, 5))

    for i, metric in enumerate(metrics):
        ax = axes[i]
        data = []
        for model in models:
            for cond in conditions:
                subset = case_df[(case_df["model"] == model) & (case_df["condition"] == cond)]
                mean_val = subset[metric].mean()
                data.append({"model": model, "condition": cond, "value": mean_val})
        plot_df = pd.DataFrame(data)
        sns.barplot(data=plot_df, x="model", y="value", hue="condition", ax=ax)
        ax.set_title(metric.replace("_", " ").title())
        ax.set_ylabel("")

    # Exec|Reasoning
    ax = axes[-1]
    data = []
    for model in models:
        for cond in conditions:
            er = compute_exec_reasoning(events, model, cond)
            data.append({"model": model, "condition": cond, "value": er})
    plot_df = pd.DataFrame(data)
    sns.barplot(data=plot_df, x="model", y="value", hue="condition", ax=ax)
    ax.set_title("Exec|Reasoning")
    ax.set_ylabel("")

    plt.tight_layout()
    plt.savefig(output_dir / "figure_1.png", dpi=150)
    plt.close()


def figure_2_delta_plot(case_df, rng, output_dir):
    """Delta plot: delta per model with CI and zero line."""
    models = sorted(case_df["model"].unique())

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(models))

    for i, model in enumerate(models):
        ci = bootstrap_ci(case_df, model, "pass_rate", rng)
        ax.bar(i, ci["mean_diff"], color="steelblue", width=0.6)
        ax.errorbar(
            i,
            ci["mean_diff"],
            yerr=[[ci["mean_diff"] - ci["ci_low"]], [ci["ci_high"] - ci["mean_diff"]]],
            color="black",
            capsize=5,
        )

    ax.axhline(y=0, color="red", linestyle="--", alpha=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=15)
    ax.set_ylabel("Delta Pass Rate (leg_reduction - baseline)")
    ax.set_title("Intervention Effect by Model")
    plt.tight_layout()
    plt.savefig(output_dir / "figure_2.png", dpi=150)
    plt.close()


def figure_3_case_heatmap(case_df, output_dir):
    """Case heatmap: rows=case_id, cols=delta metrics, sorted."""
    cases = sorted(case_df["case_id"].unique())
    rows = []
    for cid in cases:
        bl = case_df[(case_df["case_id"] == cid) & (case_df["condition"] == "baseline")]
        lr = case_df[(case_df["case_id"] == cid) & (case_df["condition"] == "leg_reduction")]
        if bl.empty or lr.empty:
            continue
        rows.append(
            {
                "case_id": cid,
                "delta_pass": lr["pass_rate"].mean() - bl["pass_rate"].mean(),
                "delta_leg": lr["leg_rate"].mean() - bl["leg_rate"].mean(),
                "delta_lucky": lr["lucky_fix_rate"].mean() - bl["lucky_fix_rate"].mean(),
            }
        )

    heatmap_df = pd.DataFrame(rows).set_index("case_id")
    heatmap_df = heatmap_df.sort_values("delta_pass")

    fig, ax = plt.subplots(figsize=(8, max(6, len(heatmap_df) * 0.25)))
    sns.heatmap(heatmap_df, annot=True, fmt=".3f", cmap="RdBu_r", center=0, ax=ax, linewidths=0.5)
    ax.set_title("Case-Level Intervention Deltas")
    plt.tight_layout()
    plt.savefig(output_dir / "figure_3.png", dpi=150)
    plt.close()


def figure_4_stability(case_df, output_dir):
    """Stability: variance distribution across trials."""
    df = case_df.copy()
    # Pass rate variance is already aggregated; compute from event-level instead
    fig, ax = plt.subplots(figsize=(8, 5))
    for cond in sorted(df["condition"].unique()):
        subset = df[df["condition"] == cond]["pass_rate"]
        ax.hist(subset, bins=20, alpha=0.5, label=cond)
    ax.set_xlabel("Case-Level Pass Rate (across trials)")
    ax.set_ylabel("Count")
    ax.set_title("Pass Rate Distribution by Condition")
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "figure_4.png", dpi=150)
    plt.close()


def figure_5_regime_map(case_df, events, output_dir):
    """Regime map: x=reasoning, y=Exec|Reasoning, color=LEG."""
    models = sorted(case_df["model"].unique())
    data = []
    for model in models:
        for cond in sorted(case_df["condition"].unique()):
            subset = case_df[(case_df["model"] == model) & (case_df["condition"] == cond)]
            reasoning_rate = subset["pass_rate"].mean()  # proxy
            er = compute_exec_reasoning(events, model, cond)
            leg = subset["leg_rate"].mean()
            data.append(
                {
                    "model": model,
                    "condition": cond,
                    "reasoning": reasoning_rate,
                    "exec_reasoning": er,
                    "leg_rate": leg,
                }
            )

    plot_df = pd.DataFrame(data)
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(
        plot_df["reasoning"],
        plot_df["exec_reasoning"],
        c=plot_df["leg_rate"],
        cmap="YlOrRd",
        s=100,
        edgecolors="black",
    )
    for _, row in plot_df.iterrows():
        ax.annotate(
            f"{row['model'][:8]}\n{row['condition'][:6]}",
            (row["reasoning"], row["exec_reasoning"]),
            fontsize=6,
            ha="center",
        )
    plt.colorbar(scatter, label="LEG Rate")
    ax.set_xlabel("Pass Rate (reasoning proxy)")
    ax.set_ylabel("Exec|Reasoning")
    ax.set_title("Regime Map")
    plt.tight_layout()
    plt.savefig(output_dir / "figure_5.png", dpi=150)
    plt.close()


# ============================================================
# TABLES
# ============================================================


def table_1_core_metrics(case_df, events, output_dir):
    """Core metrics per model × condition."""
    rows = []
    for model in sorted(case_df["model"].unique()):
        for cond in sorted(case_df["condition"].unique()):
            subset = case_df[(case_df["model"] == model) & (case_df["condition"] == cond)]
            er = compute_exec_reasoning(events, model, cond)
            rows.append(
                {
                    "model": model,
                    "condition": cond,
                    "pass_rate": round(subset["pass_rate"].mean(), 4),
                    "leg_rate": round(subset["leg_rate"].mean(), 4),
                    "lucky_fix_rate": round(subset["lucky_fix_rate"].mean(), 4),
                    "exec_reasoning": round(er, 4) if not np.isnan(er) else None,
                    "n_cases": len(subset),
                }
            )
    pd.DataFrame(rows).to_csv(output_dir / "table_1.csv", index=False)


def table_2_intervention_effects(case_df, rng, output_dir):
    """Intervention effects: deltas with CI, p-values."""
    models = sorted(case_df["model"].unique())
    rows = []
    p_values = []
    for model in models:
        for metric in ["pass_rate", "leg_rate", "lucky_fix_rate"]:
            tt = paired_ttest(case_df, model, metric)
            ci = bootstrap_ci(case_df, model, metric, rng)
            rows.append(
                {
                    "model": model,
                    "metric": metric,
                    "mean_diff": round(tt["mean_diff"], 4),
                    "t_stat": round(tt["t_stat"], 4) if tt["t_stat"] != float("inf") else "inf",
                    "p_value": round(tt["p_value"], 6),
                    "ci_low": round(ci["ci_low"], 4),
                    "ci_high": round(ci["ci_high"], 4),
                    "note": tt.get("note"),
                }
            )
            if tt["p_value"] is not None and not np.isnan(tt["p_value"]):
                p_values.append(tt["p_value"])

    # FDR correction
    if p_values:
        _, corrected, _, _ = multipletests(p_values, method="fdr_bh")
        p_idx = 0
        for row in rows:
            pv = row["p_value"]
            if isinstance(pv, (int, float)) and not np.isnan(pv):
                row["p_value_fdr"] = round(float(corrected[p_idx]), 6)
                p_idx += 1

    pd.DataFrame(rows).to_csv(output_dir / "table_2.csv", index=False)
    return rows


def table_3_stability(case_df, events, output_dir):
    """Stability: per-case variance, disagreement."""
    df = pd.DataFrame(events)
    df["is_pass"] = df["pass"].astype(bool)

    case_stability = (
        df.groupby(["case_id", "condition"])
        .agg(
            pass_var=("is_pass", "var"),
            pass_mean=("is_pass", "mean"),
            n_trials=("trial", "nunique"),
        )
        .reset_index()
    )

    # Disagreement: variance > 0 means not all trials agree
    case_stability["disagreement"] = case_stability["pass_var"] > 0
    case_stability.to_csv(output_dir / "table_3.csv", index=False)
    return case_stability


# ============================================================
# MAIN
# ============================================================


def main():
    parser = argparse.ArgumentParser(description="Paper analysis for LEG ablation")
    parser.add_argument("--input", required=True, help="Path to events_merged.jsonl")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ASSUMPTION: merge_and_validate has ensured completeness and correctness
    events = load_and_gate(input_path)
    print(f"Loaded {len(events)} events")

    # Build case-level aggregation
    case_df = build_case_level_df(events)
    print(f"Case-level df: {len(case_df)} rows")

    # Validate
    validate_stats(case_df, events)
    print("Statistical validation passed")

    # Centralized RNG — created ONCE, passed everywhere
    rng = np.random.default_rng(seed=SEED)

    # Figures
    print("Generating figures...")
    figure_1_model_condition_panel(case_df, events, output_dir, rng)
    figure_2_delta_plot(case_df, rng, output_dir)
    figure_3_case_heatmap(case_df, output_dir)
    figure_4_stability(case_df, output_dir)
    figure_5_regime_map(case_df, events, output_dir)
    print("  Figures saved: figure_1.png through figure_5.png")

    # Tables
    print("Generating tables...")
    table_1_core_metrics(case_df, events, output_dir)
    intervention_rows = table_2_intervention_effects(case_df, rng, output_dir)
    stability_df = table_3_stability(case_df, events, output_dir)
    print("  Tables saved: table_1.csv through table_3.csv")

    # Interaction analysis
    print("Running interaction analysis...")
    models = sorted(case_df["model"].unique())
    ols_result = interaction_ols(case_df, "pass_rate")

    dod_results = {}
    if len(models) >= 2:
        for i in range(len(models)):
            for j in range(i + 1, len(models)):
                key = f"{models[i]}_vs_{models[j]}"
                dod = bootstrap_dod(case_df, models[i], models[j], "pass_rate", rng)
                dod_results[key] = dod

                # Check OLS vs bootstrap agreement on direction
                ols_interaction_keys = [
                    k
                    for k in ols_result["params"]
                    if ":" in k and models[j].replace("-", "") in k.replace("-", "")
                ]
                if ols_interaction_keys:
                    ols_sign = np.sign(ols_result["params"][ols_interaction_keys[0]])
                    boot_sign = np.sign(dod["mean_dod"])
                    if ols_sign != boot_sign and ols_sign != 0 and boot_sign != 0:
                        dod_results[key]["WARNING"] = "methods disagree on interaction direction"

    # Stats summary
    print("Writing stats summary...")
    stats_summary = {
        "seed": SEED,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "n_cases": int(case_df["case_id"].nunique()),
        "n_trials": int(case_df["n_trials"].max()) if "n_trials" in case_df.columns else None,
        "n_per_condition": int(len(case_df) // len(case_df["condition"].unique())),
        "n_models": len(models),
        "models": models,
        "p_values": {},
        "ci_values": {},
        "interaction_ols": ols_result,
        "interaction_bootstrap": dod_results,
    }

    for row in intervention_rows:
        key = f"{row['model']}_{row['metric']}"
        stats_summary["p_values"][key] = row["p_value"]
        stats_summary["ci_values"][key] = {
            "ci_low": row["ci_low"],
            "ci_high": row["ci_high"],
            "mean_diff": row["mean_diff"],
        }

    with open(output_dir / "stats_summary.json", "w") as f:
        json.dump(stats_summary, f, indent=2, default=str)

    # Paper results summary
    with open(output_dir / "paper_results_summary.txt", "w") as f:
        f.write("=" * 72 + "\n")
        f.write("  PAPER RESULTS SUMMARY\n")
        f.write("=" * 72 + "\n\n")
        f.write(f"  Events: {len(events)}\n")
        f.write(f"  Models: {', '.join(models)}\n")
        f.write(f"  Cases: {case_df['case_id'].nunique()}\n")
        f.write(f"  Seed: {SEED}\n")
        f.write(f"  Bootstrap samples: {BOOTSTRAP_SAMPLES}\n\n")

        for row in intervention_rows:
            f.write(f"  {row['model']} / {row['metric']}:\n")
            f.write(f"    delta = {row['mean_diff']:.4f}\n")
            f.write(f"    p = {row['p_value']:.6f}\n")
            f.write(f"    CI = [{row['ci_low']:.4f}, {row['ci_high']:.4f}]\n")
            if row.get("note"):
                f.write(f"    note: {row['note']}\n")
            f.write("\n")

    print(f"\nAnalysis complete. Output: {output_dir}/")
    print(f"  Figures: {[f'figure_{i}.png' for i in range(1, 6)]}")
    print(f"  Tables: {[f'table_{i}.csv' for i in range(1, 4)]}")
    print(f"  Stats: stats_summary.json")
    print(f"  Summary: paper_results_summary.txt")


if __name__ == "__main__":
    main()
