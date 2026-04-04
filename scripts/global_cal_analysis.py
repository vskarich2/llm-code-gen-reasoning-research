#!/usr/bin/env python3
"""Comprehensive analysis of global calibration ablation + all post-fix case_data.

Extracts case.end events from all log directories with fixed LEG evaluator
(post commit 9175515b, March 29 2026), combines into unified DataFrame,
and produces regime classification, case/model breakdowns, and statistical
significance tests.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS = PROJECT_ROOT / "logs"

# All log directories with fixed LEG evaluator (all post March 29 2026)
# Exclude smoke tests and broken parallel smoke runs
INCLUDE_PREFIXES = [
    "global_calibration",
    "retry_critique_stage0",
    "retry_critique_stage1",
    "retry_critique_stage2",
    "stage_b_critique",
    "stage_b_critique_r2",
    "stage_c_critique",
    "v2_full_4model_10trial_canonical",
    "v2_targeted_50trial",
    "v2_anthropic_haiku45",
    "v2_anthropic_sonnet46",
    "v2_gpt5_50trial",
]

# Canonical condition names for display
CONDITION_DISPLAY = {
    "baseline_v2": "Baseline",
    "retry_bare_retry_v2": "Bare Retry",
    "leg_reduction_v2": "LEG Critique (full)",
    "leg_reduction_lean_v2": "LEG Critique (lean)",
    "retry_leg_critique_strict_v2": "Critique (strict)",
    "retry_reasoning_only_critique_v1": "Reasoning Only",
    "retry_no_contract_v2": "No Contract",
}

MODEL_SHORT = {
    "gpt-4.1-nano": "nano",
    "gpt-4o-mini": "4omini",
    "gpt-5-mini": "5mini",
    "gpt-5.4-mini": "54mini",
    "gpt-5": "gpt5",
    "claude-haiku-4-5-20251001": "haiku45",
    "claude-sonnet-4-20250514": "sonnet4",
    "claude-sonnet-4-6": "sonnet46",
    "claude-3-haiku-20240307": "haiku3",
}


def parse_events(path):
    events = []
    if not path.exists():
        return events
    for line in path.open():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            break
    return events


def extract_case_end_records(log_dir, source_label):
    """Extract case.end events from a single log directory."""
    records = []
    for events_file in sorted(log_dir.rglob("workers/*/attempt_*/events.jsonl")):
        for e in parse_events(events_file):
            if e.get("event_type") != "case.end":
                continue
            payload = e.get("payload", {})
            execution = e.get("execution", {})
            reasoning = e.get("reasoning", {})

            condition = (
                payload.get("retry_mode")
                or e.get("condition")
                or e.get("context", {}).get("condition")
            )
            # For baseline events, condition might be in context
            if not condition or condition == "null":
                condition = e.get("context", {}).get("condition") or "baseline_v2"

            records.append({
                "source": source_label,
                "case_id": e.get("case_id") or e.get("context", {}).get("case_id"),
                "model": e.get("model"),
                "trial": e.get("trial"),
                "condition": condition,
                "passed": bool(execution.get("passed")),
                "score": payload.get("score", 0),
                "mechanism_correct": bool(payload.get("mechanism_correct")),
                "reasoning_correct": bool(reasoning.get("reasoning_correct")),
                "failure_type": payload.get("failure_type") or reasoning.get("failure_type"),
                "v2_category": payload.get("v2_category") or payload.get("category"),
                "mechanism_dim": payload.get("mechanism_identified_dim"),
                "commitments_dim": payload.get("commitments_extracted_dim"),
                "satisfaction_dim": payload.get("commitments_satisfied_dim"),
                "alignment_dim": payload.get("reasoning_code_alignment_dim"),
                "retry_passed_at": payload.get("retry_passed_at"),
                "trajectory_len": len(payload.get("trajectory", [])),
            })
    return records


def load_all_data():
    """Load events from all relevant log directories."""
    all_records = []
    sources_loaded = []

    for log_subdir in sorted(LOGS.iterdir()):
        if not log_subdir.is_dir():
            continue
        name = log_subdir.name
        if not any(name.startswith(p) for p in INCLUDE_PREFIXES):
            continue

        # Check for manifest (could be top-level or in subdirs)
        manifests = list(log_subdir.glob("**/manifest.json"))
        if not manifests:
            continue

        for mf in manifests:
            run_dir = mf.parent
            try:
                mdata = json.loads(mf.read_text())
                succeeded = sum(
                    1 for v in mdata.get("work_items", {}).values()
                    if isinstance(v, dict) and v.get("state") == "SUCCEEDED"
                )
                if succeeded == 0:
                    continue
            except Exception:
                continue

            rel = str(run_dir.relative_to(LOGS))
            recs = extract_case_end_records(run_dir, rel)
            if recs:
                all_records.extend(recs)
                sources_loaded.append((rel, len(recs)))

    df = pd.DataFrame(all_records)
    return df, sources_loaded


def regime_classify(row, T=0.20):
    """Classify regime per plan Section 4."""
    if row.get("pass_base", 0) >= 0.9:
        return "Ceiling"
    d_retry = row.get("delta_retry", 0)
    d_crit = row.get("delta_crit", 0)
    d_ro = row.get("delta_ro", 0)
    if max(d_retry, d_crit, d_ro) < T:
        return "No Effect"
    if d_retry >= T and d_crit < d_retry + T and d_ro < d_retry + T:
        return "Retry-Dominant"
    if d_crit >= T and d_crit >= d_ro + T:
        return "Critique-Dominant"
    if d_ro >= T and d_ro >= d_crit + T:
        return "Reasoning-Only Dominant"
    if d_crit >= T and d_ro >= T and abs(d_crit - d_ro) < T:
        return "Intervention-Equivalent"
    return "No Effect"


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def main():
    print_section("DATA EXTRACTION")

    df, sources = load_all_data()
    print(f"Total records: {len(df)}")
    print(f"Sources loaded: {len(sources)}")
    for src, n in sources:
        print(f"  {src}: {n} events")

    if df.empty:
        print("ERROR: No case_data found")
        return

    df["model_short"] = df["model"].map(MODEL_SHORT).fillna(df["model"])
    df["cond_display"] = df["condition"].map(CONDITION_DISPLAY).fillna(df["condition"])

    # Deduplicate: same case_id + model + trial + condition should appear once
    df = df.drop_duplicates(subset=["case_id", "model", "trial", "condition"])
    print(f"After dedup: {len(df)} records")
    print(f"Models: {sorted(df['model_short'].unique())}")
    print(f"Conditions: {sorted(df['condition'].unique())}")
    print(f"Cases: {df['case_id'].nunique()}")

    # ================================================================
    # SECTION 1: OVERALL PASS RATES BY CONDITION × MODEL
    # ================================================================
    print_section("1. PASS RATES BY CONDITION × MODEL")

    pivot = df.pivot_table(
        index="model_short",
        columns="condition",
        values="passed",
        aggfunc=["mean", "count"],
    )

    # Print mean pass rates
    means = pivot["mean"]
    counts = pivot["count"]
    cond_order = [c for c in [
        "baseline_v2", "retry_bare_retry_v2",
        "leg_reduction_lean_v2", "retry_leg_critique_strict_v2",
        "retry_reasoning_only_critique_v1", "leg_reduction_v2",
    ] if c in means.columns]

    header = f"{'Model':<12}" + "".join(f"{CONDITION_DISPLAY.get(c,c):>16}" for c in cond_order)
    print(header)
    print("-" * len(header))
    for model in sorted(means.index):
        row = f"{model:<12}"
        for c in cond_order:
            if c in means.columns and not pd.isna(means.loc[model, c]):
                n = int(counts.loc[model, c])
                row += f"{means.loc[model, c]:>11.1%} ({n:>3})"
            else:
                row += f"{'—':>16}"
        print(row)

    # Overall by condition
    print(f"\n{'Overall':<12}", end="")
    for c in cond_order:
        if c in means.columns:
            m = df[df["condition"] == c]["passed"].mean()
            n = len(df[df["condition"] == c])
            print(f"{m:>11.1%} ({n:>3})", end="")
    print()

    # ================================================================
    # SECTION 2: MECHANISM CORRECTNESS (LEG) BY CONDITION × MODEL
    # ================================================================
    print_section("2. MECHANISM CORRECTNESS (LEG) BY CONDITION × MODEL")

    mech_pivot = df.pivot_table(
        index="model_short",
        columns="condition",
        values="mechanism_correct",
        aggfunc="mean",
    )

    header = f"{'Model':<12}" + "".join(f"{CONDITION_DISPLAY.get(c,c):>16}" for c in cond_order)
    print(header)
    print("-" * len(header))
    for model in sorted(mech_pivot.index):
        row = f"{model:<12}"
        for c in cond_order:
            if c in mech_pivot.columns and not pd.isna(mech_pivot.loc[model, c]):
                row += f"{mech_pivot.loc[model, c]:>16.1%}"
            else:
                row += f"{'—':>16}"
        print(row)

    # ================================================================
    # SECTION 3: LEG RATE (mechanism_correct AND NOT passed)
    # ================================================================
    print_section("3. LEG RATE (correct reasoning, wrong code) BY CONDITION × MODEL")

    df["leg_true"] = df["mechanism_correct"] & ~df["passed"]

    leg_pivot = df.pivot_table(
        index="model_short",
        columns="condition",
        values="leg_true",
        aggfunc="mean",
    )

    header = f"{'Model':<12}" + "".join(f"{CONDITION_DISPLAY.get(c,c):>16}" for c in cond_order)
    print(header)
    print("-" * len(header))
    for model in sorted(leg_pivot.index):
        row = f"{model:<12}"
        for c in cond_order:
            if c in leg_pivot.columns and not pd.isna(leg_pivot.loc[model, c]):
                row += f"{leg_pivot.loc[model, c]:>16.1%}"
            else:
                row += f"{'—':>16}"
        print(row)

    # ================================================================
    # SECTION 4: CASE-LEVEL ANALYSIS (hardest and most LEG-susceptible)
    # ================================================================
    print_section("4. CASE-LEVEL ANALYSIS")

    # Baseline pass rates by case (across all models)
    baseline = df[df["condition"] == "baseline_v2"]
    if len(baseline) > 0:
        case_baseline = baseline.groupby("case_id").agg(
            pass_rate=("passed", "mean"),
            leg_rate=("leg_true", "mean"),
            mechanism_rate=("mechanism_correct", "mean"),
            n_trials=("passed", "count"),
        ).sort_values("pass_rate")

        print("Top 15 hardest cases (baseline pass rate):")
        print(f"{'Case':<30} {'Pass%':>8} {'LEG%':>8} {'Mech%':>8} {'N':>6}")
        print("-" * 62)
        for cid, row in case_baseline.head(15).iterrows():
            print(f"{cid:<30} {row['pass_rate']:>7.1%} {row['leg_rate']:>7.1%} "
                  f"{row['mechanism_rate']:>7.1%} {int(row['n_trials']):>6}")

        print(f"\nTop 10 highest LEG rate cases:")
        case_by_leg = case_baseline.sort_values("leg_rate", ascending=False)
        print(f"{'Case':<30} {'Pass%':>8} {'LEG%':>8} {'Mech%':>8} {'N':>6}")
        print("-" * 62)
        for cid, row in case_by_leg.head(10).iterrows():
            print(f"{cid:<30} {row['pass_rate']:>7.1%} {row['leg_rate']:>7.1%} "
                  f"{row['mechanism_rate']:>7.1%} {int(row['n_trials']):>6}")

    # ================================================================
    # SECTION 5: INTERVENTION DELTAS (treatment - baseline)
    # ================================================================
    print_section("5. INTERVENTION DELTAS (pass rate: treatment - baseline)")

    treatments = [c for c in cond_order if c != "baseline_v2"]

    # Per model × case pass rates
    pair_rates = df.groupby(["case_id", "model_short", "condition"])["passed"].mean().reset_index()
    pair_rates = pair_rates.rename(columns={"passed": "pass_rate"})

    base_rates = pair_rates[pair_rates["condition"] == "baseline_v2"][
        ["case_id", "model_short", "pass_rate"]
    ].rename(columns={"pass_rate": "pass_base"})

    if len(base_rates) > 0:
        for treat in treatments:
            treat_rates = pair_rates[pair_rates["condition"] == treat][
                ["case_id", "model_short", "pass_rate"]
            ].rename(columns={"pass_rate": f"pass_{treat}"})

            merged = base_rates.merge(treat_rates, on=["case_id", "model_short"], how="inner")
            if merged.empty:
                continue
            merged["delta"] = merged[f"pass_{treat}"] - merged["pass_base"]
            disp = CONDITION_DISPLAY.get(treat, treat)
            mean_d = merged["delta"].mean()
            med_d = merged["delta"].median()
            pos = (merged["delta"] > 0).sum()
            neg = (merged["delta"] < 0).sum()
            zero = (merged["delta"] == 0).sum()
            n = len(merged)

            # Wilcoxon signed-rank test
            nonzero = merged["delta"][merged["delta"] != 0]
            if len(nonzero) >= 10:
                w_stat, w_p = stats.wilcoxon(nonzero)
            else:
                w_stat, w_p = float("nan"), float("nan")

            print(f"{disp:<25} mean={mean_d:>+.3f}  median={med_d:>+.3f}  "
                  f"+{pos}/-{neg}/={zero}  N={n}  Wilcoxon p={w_p:.4f}")

    # ================================================================
    # SECTION 6: REGIME CLASSIFICATION (per plan Section 4)
    # ================================================================
    print_section("6. REGIME CLASSIFICATION")

    # Need: pass_base, pass_retry, pass_crit, pass_ro per (case, model) pair
    retry_col = "retry_bare_retry_v2"
    crit_col = "retry_leg_critique_strict_v2"
    ro_col = "retry_reasoning_only_critique_v1"

    regime_pairs = base_rates.copy()
    for cond, label in [(retry_col, "retry"), (crit_col, "crit"), (ro_col, "ro")]:
        treat = pair_rates[pair_rates["condition"] == cond][
            ["case_id", "model_short", "pass_rate"]
        ].rename(columns={"pass_rate": f"pass_{label}"})
        regime_pairs = regime_pairs.merge(treat, on=["case_id", "model_short"], how="left")

    # Only classify pairs that have all 4 arms
    regime_full = regime_pairs.dropna(subset=["pass_retry", "pass_crit", "pass_ro"])

    if len(regime_full) > 0:
        regime_full["delta_retry"] = regime_full["pass_retry"] - regime_full["pass_base"]
        regime_full["delta_crit"] = regime_full["pass_crit"] - regime_full["pass_base"]
        regime_full["delta_ro"] = regime_full["pass_ro"] - regime_full["pass_base"]
        regime_full["regime"] = regime_full.apply(regime_classify, axis=1)

        # Global distribution
        regime_dist = regime_full["regime"].value_counts()
        total_pairs = len(regime_full)
        print(f"Total case×model pairs with all 4 arms: {total_pairs}\n")
        print(f"{'Regime':<28} {'Count':>6} {'%':>8}")
        print("-" * 44)
        for regime in ["No Effect", "Ceiling", "Retry-Dominant",
                       "Critique-Dominant", "Reasoning-Only Dominant",
                       "Intervention-Equivalent"]:
            cnt = regime_dist.get(regime, 0)
            print(f"{regime:<28} {cnt:>6} {cnt/total_pairs:>7.1%}")

        # By model
        print(f"\nRegime distribution by model:")
        model_regime = pd.crosstab(
            regime_full["model_short"], regime_full["regime"],
            margins=True, margins_name="Total",
        )
        # Normalize to percentages
        model_regime_pct = model_regime.div(model_regime["Total"], axis=0) * 100
        print(model_regime_pct.round(1).to_string())

        # By case (top cases where critique or reasoning-only dominates)
        print(f"\n\nCases where Critique dominates (>= 1 model):")
        crit_cases = regime_full[regime_full["regime"] == "Critique-Dominant"]
        if len(crit_cases) > 0:
            for cid in sorted(crit_cases["case_id"].unique()):
                subset = crit_cases[crit_cases["case_id"] == cid]
                models = ", ".join(sorted(subset["model_short"]))
                avg_delta = subset["delta_crit"].mean()
                print(f"  {cid:<30} models=[{models}]  avg Δcrit={avg_delta:+.2f}")

        print(f"\nCases where Reasoning-Only dominates (>= 1 model):")
        ro_cases = regime_full[regime_full["regime"] == "Reasoning-Only Dominant"]
        if len(ro_cases) > 0:
            for cid in sorted(ro_cases["case_id"].unique()):
                subset = ro_cases[ro_cases["case_id"] == cid]
                models = ", ".join(sorted(subset["model_short"]))
                avg_delta = subset["delta_ro"].mean()
                print(f"  {cid:<30} models=[{models}]  avg Δro={avg_delta:+.2f}")

    # ================================================================
    # SECTION 7: CASE CLUSTER ANALYSIS
    # ================================================================
    print_section("7. CASE CLUSTER ANALYSIS")

    # Define clusters from plan Section 5.C
    CLUSTERS = {
        "Severe LEG": ["feature_flag_drift", "false_fix_deadlock"],
        "Moderate LEG": [
            "check_then_act", "overdetermination", "missing_branch_c",
            "hidden_dep_multihop", "config_shadowing", "invariant_partial_fail",
            "async_race_lock", "lost_update",
        ],
        "Partial-dominated": ["invariant_partial_fail", "config_shadowing"],
        "Reasoning-limited": ["l3_state_pipeline", "async_race_lock"],
        "Lucky fix": [
            "cache_invalidation_order", "use_before_set_a",
            "use_before_set_b", "use_before_set_c",
        ],
    }

    def get_cluster(case_id):
        for cluster, cases in CLUSTERS.items():
            if case_id in cases:
                return cluster
        return "Capable"

    if len(regime_full) > 0:
        regime_full = regime_full.copy()
        regime_full["cluster"] = regime_full["case_id"].apply(get_cluster)

        cluster_regime = pd.crosstab(
            regime_full["cluster"], regime_full["regime"],
            margins=True, margins_name="Total",
        )
        cluster_regime_pct = cluster_regime.div(cluster_regime["Total"], axis=0) * 100
        print(cluster_regime_pct.round(1).to_string())

        # Cluster-level pass rate deltas
        print(f"\n\nMean deltas by cluster:")
        print(f"{'Cluster':<22} {'Δretry':>8} {'Δcrit':>8} {'Δro':>8} {'N':>6}")
        print("-" * 56)
        for cluster in ["Severe LEG", "Moderate LEG", "Reasoning-limited",
                        "Lucky fix", "Capable"]:
            sub = regime_full[regime_full["cluster"] == cluster]
            if len(sub) == 0:
                continue
            print(f"{cluster:<22} {sub['delta_retry'].mean():>+7.3f} "
                  f"{sub['delta_crit'].mean():>+7.3f} "
                  f"{sub['delta_ro'].mean():>+7.3f} {len(sub):>6}")

    # ================================================================
    # SECTION 8: LEG × REGIME CROSS-TABULATION
    # ================================================================
    print_section("8. LEG SEVERITY × INTERVENTION REGIME")

    if len(base_rates) > 0 and len(regime_full) > 0:
        # Compute LEG rate from baseline case_data per (case, model)
        baseline_leg = df[df["condition"] == "baseline_v2"].groupby(
            ["case_id", "model_short"]
        )["leg_true"].mean().reset_index().rename(columns={"leg_true": "leg_rate"})

        regime_with_leg = regime_full.merge(
            baseline_leg, on=["case_id", "model_short"], how="left"
        )

        def leg_bucket(r):
            if pd.isna(r):
                return "unknown"
            if r > 0.30:
                return "LEG>30%"
            if r > 0.10:
                return "LEG 10-30%"
            if r > 0.01:
                return "LEG <10%"
            return "LEG≈0%"

        regime_with_leg["leg_bucket"] = regime_with_leg["leg_rate"].apply(leg_bucket)

        cross = pd.crosstab(
            regime_with_leg["regime"], regime_with_leg["leg_bucket"],
            margins=True, margins_name="Total",
        )
        print(cross.to_string())

    # ================================================================
    # SECTION 9: STATISTICAL SIGNIFICANCE TESTS
    # ================================================================
    print_section("9. STATISTICAL SIGNIFICANCE")

    # For each treatment vs baseline, run:
    # 1. Paired t-test on (case, model) pass rates
    # 2. Wilcoxon signed-rank test
    # 3. Chi-squared test on overall pass counts
    # 4. Bootstrap CI for mean delta

    rng = np.random.default_rng(42)

    for treat in treatments:
        treat_rates_df = pair_rates[pair_rates["condition"] == treat][
            ["case_id", "model_short", "pass_rate"]
        ].rename(columns={"pass_rate": "pass_treat"})

        merged = base_rates.merge(treat_rates_df, on=["case_id", "model_short"], how="inner")
        if len(merged) < 5:
            continue
        merged["delta"] = merged["pass_treat"] - merged["pass_base"]

        disp = CONDITION_DISPLAY.get(treat, treat)
        print(f"\n--- {disp} vs Baseline (N={len(merged)} pairs) ---")
        print(f"  Mean Δ = {merged['delta'].mean():+.4f} "
              f"(SE={merged['delta'].std()/np.sqrt(len(merged)):.4f})")

        # Paired t-test
        t_stat, t_p = stats.ttest_1samp(merged["delta"], 0)
        print(f"  Paired t-test:    t={t_stat:.3f}, p={t_p:.4f} "
              f"{'***' if t_p<0.001 else '**' if t_p<0.01 else '*' if t_p<0.05 else 'ns'}")

        # Wilcoxon
        nonzero = merged["delta"][merged["delta"] != 0]
        if len(nonzero) >= 10:
            w_stat, w_p = stats.wilcoxon(nonzero)
            print(f"  Wilcoxon:         W={w_stat:.0f}, p={w_p:.4f} "
                  f"{'***' if w_p<0.001 else '**' if w_p<0.01 else '*' if w_p<0.05 else 'ns'}")

        # Bootstrap 95% CI
        boot_means = []
        for _ in range(5000):
            sample = rng.choice(merged["delta"].values, size=len(merged), replace=True)
            boot_means.append(np.mean(sample))
        boot_means = np.array(boot_means)
        ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
        print(f"  Bootstrap 95% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}]")

        # Per-model breakdown
        print(f"  Per-model deltas:")
        for model in sorted(merged["model_short"].unique()):
            sub = merged[merged["model_short"] == model]
            d = sub["delta"].mean()
            n = len(sub)
            if n >= 3:
                _, mp = stats.ttest_1samp(sub["delta"], 0)
                sig = '***' if mp < 0.001 else '**' if mp < 0.01 else '*' if mp < 0.05 else 'ns'
            else:
                mp = float("nan")
                sig = "n/a"
            print(f"    {model:<12} Δ={d:>+.3f} (N={n:>3})  p={mp:.3f} {sig}")

    # ================================================================
    # SECTION 10: CRITIQUE vs REASONING-ONLY HEAD-TO-HEAD
    # ================================================================
    print_section("10. CRITIQUE vs REASONING-ONLY (head-to-head)")

    if crit_col in df["condition"].values and ro_col in df["condition"].values:
        crit_rates = pair_rates[pair_rates["condition"] == crit_col][
            ["case_id", "model_short", "pass_rate"]
        ].rename(columns={"pass_rate": "pass_crit"})

        ro_rates = pair_rates[pair_rates["condition"] == ro_col][
            ["case_id", "model_short", "pass_rate"]
        ].rename(columns={"pass_rate": "pass_ro"})

        h2h = crit_rates.merge(ro_rates, on=["case_id", "model_short"], how="inner")
        if len(h2h) > 0:
            h2h["delta_crit_ro"] = h2h["pass_crit"] - h2h["pass_ro"]

            crit_wins = (h2h["delta_crit_ro"] > 0.05).sum()
            ro_wins = (h2h["delta_crit_ro"] < -0.05).sum()
            ties = len(h2h) - crit_wins - ro_wins
            print(f"Pairs: {len(h2h)}")
            print(f"Critique wins (>5pp): {crit_wins} ({crit_wins/len(h2h):.1%})")
            print(f"R-only wins (>5pp):   {ro_wins} ({ro_wins/len(h2h):.1%})")
            print(f"Ties (within 5pp):    {ties} ({ties/len(h2h):.1%})")
            print(f"Mean Δ(crit-ro):      {h2h['delta_crit_ro'].mean():+.4f}")

            # Paired test
            nonzero = h2h["delta_crit_ro"][h2h["delta_crit_ro"] != 0]
            if len(nonzero) >= 10:
                w_stat, w_p = stats.wilcoxon(nonzero)
                print(f"Wilcoxon p={w_p:.4f} "
                      f"{'***' if w_p<0.001 else '**' if w_p<0.01 else '*' if w_p<0.05 else 'ns'}")

            print(f"\nPer-model:")
            for model in sorted(h2h["model_short"].unique()):
                sub = h2h[h2h["model_short"] == model]
                d = sub["delta_crit_ro"].mean()
                cw = (sub["delta_crit_ro"] > 0.05).sum()
                rw = (sub["delta_crit_ro"] < -0.05).sum()
                print(f"  {model:<12} Δ={d:>+.3f}  crit_wins={cw}  ro_wins={rw}  N={len(sub)}")

    # ================================================================
    # SECTION 11: v2 CATEGORY DISTRIBUTION
    # ================================================================
    print_section("11. OUTCOME CATEGORY DISTRIBUTION BY CONDITION")

    cat_dist = df.groupby(["condition", "v2_category"]).size().unstack(fill_value=0)
    cat_pct = cat_dist.div(cat_dist.sum(axis=1), axis=0) * 100
    print(cat_pct.round(1).to_string())

    print("\n\nDone.")


if __name__ == "__main__":
    main()
