#!/usr/bin/env python3
"""Full research analysis run across all experiment logs.

Produces decision-grade snapshot answering:
- Where does LEG actually help vs hurt?
- Which cases exhibit true reasoning→execution gaps?
- How much of the observed effect is real vs artifact?
- Where should we expand cases next?
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

from artifacts.analysis.load_logs import load_logs, prepare_df

pd.set_option("display.max_rows", 200)
pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 160)
pd.set_option("display.float_format", lambda x: f"{x:.4f}")

# -----------------------------------------------------------------------
# All log directories
# -----------------------------------------------------------------------
LOG_DIRS = [
    # Global Calibration
    "logs/global_calibration/haiku45",
    "logs/global_calibration/sonnet46",
    "logs/global_calibration/nano",
    "logs/global_calibration/4omini",
    "logs/global_calibration/sonnet4",
    "logs/global_calibration/5mini",
    "logs/global_calibration/54mini",
    "logs/global_calibration/gpt5",
    # Retry Critique Stage 0
    "logs/retry_critique_stage0",
    "logs/retry_critique_stage0_anthropic",
    # Retry Critique Stage 1
    "logs/retry_critique_stage1/anthropic_sonnet",
    "logs/retry_critique_stage1/openai_gpt5",
    "logs/retry_critique_stage1/anthropic_haiku",
    "logs/retry_critique_stage1/openai_4omini",
    "logs/retry_critique_stage1/openai_nano",
    "logs/retry_critique_stage1/openai_5mini",
    "logs/retry_critique_stage1/openai_54mini",
    # Retry Critique Stage 2
    "logs/retry_critique_stage2/anthropic_sonnet",
    "logs/retry_critique_stage2/anthropic_haiku",
    "logs/retry_critique_stage2/openai_4omini",
    "logs/retry_critique_stage2/openai_nano",
    "logs/retry_critique_stage2/openai_5mini",
    "logs/retry_critique_stage2/openai_54mini",
    # Stage B Critique
    "logs/stage_b_critique/openai_4omini",
    "logs/stage_b_critique/openai_54mini",
    "logs/stage_b_critique_r2/openai_4omini",
    "logs/stage_b_critique_r2/openai_54mini",
    # Stage C Critique
    "logs/stage_c_critique/openai_4omini",
    "logs/stage_c_critique/openai_nano",
    "logs/stage_c_critique/openai_5mini",
    "logs/stage_c_critique/openai_54mini",
    # V2 Oracle Intervention
    "logs/v2_anthropic_haiku45",
    "logs/v2_anthropic_sonnet46",
    "logs/v2_anthropic_sonnet46_v2",
    "logs/v2_anthropic_sonnet46_v3",
    "logs/v2_gpt5_50trial",
    "logs/v2_gpt5_50trial_v2",
    # V2 Canonical
    "logs/v2_full_4model_10trial_canonical",
    # V2 Targeted 50-trial
    "logs/v2_targeted_50trial_canonical",
    "logs/v2_targeted_50trial_tranche2",
    "logs/v2_targeted_50trial_tranche3",
    "logs/v2_targeted_50trial_tranche4",
]

ARTIFACT_THRESHOLD = 0.05  # delta below this in parse-conditioned = ~0
SIGNIFICANT_THRESHOLD = 0.10  # +/-10pp for help/harm classification
LEG_SUFFERING_THRESHOLD = 0.40  # baseline LEG rate threshold


def header(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def subheader(title):
    print(f"\n--- {title} ---\n")


def paired_rates(df, cond_a, cond_b):
    """Compute paired pass/LEG rates for two conditions.

    Returns DataFrame indexed by (case_id, model) with baseline/treatment
    rates and deltas.
    """
    idx = ["case_id", "model", "trial_idx"]
    keep = ["case_id", "model", "trial_idx", "pass", "reasoning_correct",
            "leg_true"]
    a = df[df["condition"] == cond_a][keep].set_index(idx)
    b = df[df["condition"] == cond_b][keep].set_index(idx)
    paired = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
    if len(paired) == 0:
        return pd.DataFrame()
    paired = paired.reset_index()
    # Aggregate per (case_id, model)
    g = paired.groupby(["case_id", "model"])
    result = pd.DataFrame({
        "baseline_pass": g["pass_a"].mean(),
        "treatment_pass": g["pass_b"].mean(),
        "pass_delta": g.apply(
            lambda x: (x["pass_b"] - x["pass_a"]).mean(),
            include_groups=False),
        "baseline_leg": g["leg_true_a"].mean(),
        "treatment_leg": g["leg_true_b"].mean(),
        "leg_delta": g.apply(
            lambda x: (x["leg_true_b"] - x["leg_true_a"]).mean(),
            include_groups=False),
        "baseline_reasoning": g["reasoning_correct_a"].mean(),
        "treatment_reasoning": g["reasoning_correct_b"].mean(),
        "reasoning_delta": g.apply(
            lambda x: (x["reasoning_correct_b"]
                       - x["reasoning_correct_a"]).mean(),
            include_groups=False),
        "paired_count": g["pass_a"].count(),
    })
    return result


def run_analysis_1(df):
    """ANALYSIS 1 — DATA INTEGRITY REPORT."""
    header("ANALYSIS 1 — DATA INTEGRITY REPORT")

    subheader("Dataset Summary")
    print(f"Total rows: {len(df)}")
    print(f"\nRows per condition:")
    print(df["condition"].value_counts().to_string())
    print(f"\nRows per model:")
    print(df["model"].value_counts().to_string())
    print(f"\nRows per (model, condition):")
    mc = df.groupby(["model", "condition"]).size()
    print(mc.to_string())

    subheader("Pairing Integrity")
    conditions = df["condition"].unique().tolist()
    baselines = [c for c in conditions if "baseline" in c]
    treatments = [c for c in conditions if c not in baselines]
    for b in sorted(baselines):
        for t in sorted(treatments):
            # Check if they share any case_ids
            b_cases = set(df[df["condition"] == b]["case_id"])
            t_cases = set(df[df["condition"] == t]["case_id"])
            overlap = b_cases & t_cases
            if not overlap:
                continue
            idx = ["case_id", "model", "trial_idx"]
            a = df[df["condition"] == b].set_index(idx)
            bdf = df[df["condition"] == t].set_index(idx)
            inner = a.index.intersection(bdf.index)
            only_a = len(a.index.difference(bdf.index))
            only_b = len(bdf.index.difference(a.index))
            print(f"  {b} vs {t}: {len(inner)} paired | "
                  f"{only_a} unpaired-baseline | {only_b} unpaired-treatment")

    subheader("Parse Success Rate")
    if "parse_success" in df.columns and df["parse_success"].notna().any():
        ps = df.groupby(["model", "condition"])["parse_success"].mean()
        print(ps.to_string())
    else:
        print("parse_success not available in this dataset")


def run_analysis_2(df, df_strict, comparisons):
    """ANALYSIS 2 — CORE PAIRED DELTAS."""
    header("ANALYSIS 2 — CORE PAIRED DELTAS")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")

        for tag, dframe in [("STRICT (all rows)", df_strict),
                            ("PARSE-CONDITIONED", df)]:
            print(f"\n  [{tag}]")
            pr = paired_rates(dframe, cond_a, cond_b)
            if pr.empty:
                print("    No paired case_data available")
                continue
            n = pr["paired_count"].sum()
            print(f"    Total paired trials: {int(n)}")
            print(f"    Pass rate:  baseline={pr['baseline_pass'].mean():.3f}"
                  f"  treatment={pr['treatment_pass'].mean():.3f}"
                  f"  Δ={pr['pass_delta'].mean():+.3f}")
            print(f"    LEG rate:   baseline={pr['baseline_leg'].mean():.3f}"
                  f"  treatment={pr['treatment_leg'].mean():.3f}"
                  f"  Δ={pr['leg_delta'].mean():+.3f}")

            # By model
            for model, mdf in pr.groupby("model"):
                print(f"      {model:20s}  "
                      f"pass Δ={mdf['pass_delta'].mean():+.3f}  "
                      f"LEG Δ={mdf['leg_delta'].mean():+.3f}  "
                      f"n={int(mdf['paired_count'].sum())}")


def run_analysis_3(df, comparisons):
    """ANALYSIS 3 — CASE × MODEL DELTA TABLE."""
    header("ANALYSIS 3 — CASE × MODEL DELTA TABLE")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            print("No paired case_data available")
            continue
        # Join family
        family_map = df[["case_id", "family"]].drop_duplicates().set_index(
            "case_id")["family"]
        display = pr.copy()
        display["family"] = display.index.get_level_values(
            "case_id").map(family_map)
        cols = ["family", "baseline_pass", "treatment_pass", "pass_delta",
                "baseline_leg", "treatment_leg", "leg_delta", "paired_count"]
        print(display[cols].to_string())


def run_analysis_4(df, df_strict, comparisons):
    """ANALYSIS 4 — RECONSTRUCTION ARTIFACT DETECTION."""
    header("ANALYSIS 4 — RECONSTRUCTION ARTIFACT DETECTION")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        strict = paired_rates(df_strict, cond_a, cond_b)
        parsed = paired_rates(df, cond_a, cond_b)
        if strict.empty or parsed.empty:
            print("Insufficient case_data")
            continue

        # Align indices
        common = strict.index.intersection(parsed.index)
        s = strict.loc[common, "pass_delta"]
        p = parsed.loc[common, "pass_delta"]

        categories = []
        for idx in common:
            sv, pv = s[idx], p[idx]
            if sv > ARTIFACT_THRESHOLD and pv > ARTIFACT_THRESHOLD:
                cat = "REAL_HELP"
            elif sv < -ARTIFACT_THRESHOLD and pv < -ARTIFACT_THRESHOLD:
                cat = "REAL_HARM"
            elif sv > ARTIFACT_THRESHOLD and abs(pv) <= ARTIFACT_THRESHOLD:
                cat = "ARTIFACT_HELP"
            elif sv < -ARTIFACT_THRESHOLD and abs(pv) <= ARTIFACT_THRESHOLD:
                cat = "ARTIFACT_HARM"
            else:
                cat = "MIXED/UNCLEAR"
            categories.append({"case_id": idx[0], "model": idx[1],
                               "strict_delta": sv, "parsed_delta": pv,
                               "category": cat})
        cats = pd.DataFrame(categories)

        print("Summary counts:")
        print(cats["category"].value_counts().to_string())

        for cat_name in ["ARTIFACT_HELP", "ARTIFACT_HARM",
                         "REAL_HELP", "REAL_HARM"]:
            sub = cats[cats["category"] == cat_name].sort_values(
                "strict_delta", ascending=(cat_name.endswith("HARM")))
            if len(sub) > 0:
                print(f"\n  Top {cat_name} examples:")
                print(sub.head(5).to_string(index=False))


def run_analysis_5(df, comparisons):
    """ANALYSIS 5 — LEG-SUFFERING CASE IDENTIFICATION."""
    header("ANALYSIS 5 — LEG-SUFFERING CASE IDENTIFICATION")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            print("No case_data")
            continue

        suffering = pr[pr["baseline_leg"] >= LEG_SUFFERING_THRESHOLD].copy()
        print(f"LEG-suffering (case, model) pairs "
              f"(baseline LEG ≥ {LEG_SUFFERING_THRESHOLD}): "
              f"{len(suffering)}")

        if len(suffering) == 0:
            continue

        suffering["leg_drop"] = -suffering["leg_delta"]
        suffering["pass_increase"] = suffering["pass_delta"]
        suffering["conversion_ratio"] = np.where(
            suffering["leg_drop"] > 0,
            suffering["pass_increase"] / suffering["leg_drop"],
            np.nan
        )

        cols = ["baseline_pass", "baseline_leg", "leg_drop",
                "pass_increase", "conversion_ratio", "paired_count"]
        print(suffering[cols].to_string())

        improved = (suffering["pass_increase"] > SIGNIFICANT_THRESHOLD).sum()
        worsened = (suffering["pass_increase"] < -SIGNIFICANT_THRESHOLD).sum()
        unchanged = len(suffering) - improved - worsened
        print(f"\n  Improved (>+10pp): {improved}/{len(suffering)} "
              f"({improved/len(suffering)*100:.1f}%)")
        print(f"  Unchanged:        {unchanged}/{len(suffering)} "
              f"({unchanged/len(suffering)*100:.1f}%)")
        print(f"  Worsened (<-10pp): {worsened}/{len(suffering)} "
              f"({worsened/len(suffering)*100:.1f}%)")


def run_analysis_6(df, comparisons):
    """ANALYSIS 6 — HETEROGENEITY."""
    header("ANALYSIS 6 — HETEROGENEITY")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            print("No case_data")
            continue

        family_map = df[["case_id", "family"]].drop_duplicates().set_index(
            "case_id")["family"]

        records = []
        for case_id, grp in pr.groupby("case_id"):
            deltas = grp["pass_delta"]
            n_helped = (deltas > SIGNIFICANT_THRESHOLD).sum()
            n_hurt = (deltas < -SIGNIFICANT_THRESHOLD).sum()
            records.append({
                "case_id": case_id,
                "family": family_map.get(case_id, "?"),
                "n_models_helped": int(n_helped),
                "n_models_hurt": int(n_hurt),
                "heterogeneous": n_helped > 0 and n_hurt > 0,
                "mean_abs_delta": deltas.abs().mean(),
            })
        het = pd.DataFrame(records).set_index("case_id")

        print("Case heterogeneity table:")
        print(het.to_string())

        n_het = het["heterogeneous"].sum()
        print(f"\nOverall: {n_het}/{len(het)} cases heterogeneous "
              f"({n_het/len(het)*100:.1f}%)")

        subheader("Family summary")
        fam = het.groupby("family").agg(
            n_cases=("heterogeneous", "count"),
            n_heterogeneous=("heterogeneous", "sum"),
            pct_heterogeneous=("heterogeneous", "mean"),
            avg_abs_delta=("mean_abs_delta", "mean"),
        )
        fam["pct_heterogeneous"] = fam["pct_heterogeneous"] * 100
        print(fam.sort_values("pct_heterogeneous", ascending=False).to_string())


def run_analysis_7(df, comparisons):
    """ANALYSIS 7 — FAMILY-LEVEL EFFECTS."""
    header("ANALYSIS 7 — FAMILY-LEVEL EFFECTS")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            print("No case_data")
            continue

        family_map = df[["case_id", "family"]].drop_duplicates().set_index(
            "case_id")["family"]
        pr_f = pr.copy()
        pr_f["family"] = pr_f.index.get_level_values("case_id").map(
            family_map)

        fam = pr_f.groupby("family").agg(
            mean_pass_delta=("pass_delta", "mean"),
            mean_leg_delta=("leg_delta", "mean"),
            n_case_model=("pass_delta", "count"),
            n_sig_helps=("pass_delta",
                         lambda x: (x > SIGNIFICANT_THRESHOLD).sum()),
            n_sig_harms=("pass_delta",
                         lambda x: (x < -SIGNIFICANT_THRESHOLD).sum()),
        )
        fam["n_cases"] = pr_f.groupby("family").apply(
            lambda x: x.index.get_level_values("case_id").nunique(),
            include_groups=False)
        fam["n_models"] = pr_f.groupby("family").apply(
            lambda x: x.index.get_level_values("model").nunique(),
            include_groups=False)
        print(fam.sort_values("mean_pass_delta", ascending=False).to_string())


def run_analysis_8(df, comparisons):
    """ANALYSIS 8 — MODEL-SPECIFIC BEHAVIOR."""
    header("ANALYSIS 8 — MODEL-SPECIFIC BEHAVIOR")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            print("No case_data")
            continue

        for model, mdf in pr.groupby("model"):
            n_total = len(mdf)
            n_helped = (mdf["pass_delta"] > SIGNIFICANT_THRESHOLD).sum()
            n_hurt = (mdf["pass_delta"] < -SIGNIFICANT_THRESHOLD).sum()
            # Conversion: cases where LEG dropped and pass increased
            converting = mdf[
                (mdf["leg_delta"] < 0) & (mdf["pass_delta"] > 0)]
            print(f"  {model}:")
            print(f"    pass Δ mean={mdf['pass_delta'].mean():+.3f}  "
                  f"LEG Δ mean={mdf['leg_delta'].mean():+.3f}")
            print(f"    helped(>+10pp): {n_helped}/{n_total} "
                  f"({n_helped/n_total*100:.1f}%)")
            print(f"    hurt(<-10pp):   {n_hurt}/{n_total} "
                  f"({n_hurt/n_total*100:.1f}%)")
            print(f"    LEG→pass converting: {len(converting)}/{n_total} "
                  f"({len(converting)/n_total*100:.1f}%)")
            print()


def run_analysis_9(df, lean_comp, leg_comp):
    """ANALYSIS 9 — LEAN VS FULL LEG COMPARISON."""
    header("ANALYSIS 9 — LEAN VS FULL LEG COMPARISON")

    if lean_comp is None or leg_comp is None:
        print("Need both LEAN and LEG comparisons")
        return

    _, lean_a, lean_b = lean_comp
    _, leg_a, leg_b = leg_comp

    pr_lean = paired_rates(df, lean_a, lean_b)
    pr_leg = paired_rates(df, leg_a, leg_b)

    if pr_lean.empty or pr_leg.empty:
        print("Insufficient case_data for comparison")
        return

    common = pr_lean.index.intersection(pr_leg.index)
    if len(common) == 0:
        print("No overlapping (case_id, model) pairs")
        return

    lean_d = pr_lean.loc[common, "pass_delta"]
    leg_d = pr_leg.loc[common, "pass_delta"]

    lean_wins = (lean_d > leg_d + ARTIFACT_THRESHOLD).sum()
    leg_wins = (leg_d > lean_d + ARTIFACT_THRESHOLD).sum()
    ties = len(common) - lean_wins - leg_wins

    print(f"Across {len(common)} (case_id, model) pairs:")
    print(f"  LEAN > LEG:  {lean_wins} ({lean_wins/len(common)*100:.1f}%)")
    print(f"  LEG > LEAN:  {leg_wins} ({leg_wins/len(common)*100:.1f}%)")
    print(f"  Tie (~equal): {ties} ({ties/len(common)*100:.1f}%)")
    print(f"\n  Mean pass_delta LEAN: {lean_d.mean():+.4f}")
    print(f"  Mean pass_delta LEG:  {leg_d.mean():+.4f}")
    print(f"  Mean difference (LEAN - LEG): {(lean_d - leg_d).mean():+.4f}")

    # Cases where LEAN massively outperforms LEG
    diff = lean_d - leg_d
    massive_lean = diff[diff > 0.20]
    massive_leg = diff[diff < -0.20]
    if len(massive_lean) > 0:
        subheader("Cases where LEAN >> LEG (>20pp)")
        for idx in massive_lean.sort_values(ascending=False).head(10).index:
            print(f"  {idx[0]:30s} {idx[1]:20s}  "
                  f"LEAN Δ={lean_d[idx]:+.3f}  LEG Δ={leg_d[idx]:+.3f}  "
                  f"diff={diff[idx]:+.3f}")
    if len(massive_leg) > 0:
        subheader("Cases where LEG >> LEAN (>20pp)")
        for idx in massive_leg.sort_values().head(10).index:
            print(f"  {idx[0]:30s} {idx[1]:20s}  "
                  f"LEAN Δ={lean_d[idx]:+.3f}  LEG Δ={leg_d[idx]:+.3f}  "
                  f"diff={diff[idx]:+.3f}")


def run_analysis_10(df, comparisons):
    """ANALYSIS 10 — TOP CASES."""
    header("ANALYSIS 10 — TOP CASES")

    for label, cond_a, cond_b in comparisons:
        subheader(f"{label}: {cond_a} vs {cond_b}")
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            print("No case_data")
            continue

        family_map = df[["case_id", "family"]].drop_duplicates().set_index(
            "case_id")["family"]

        for tag, ascending, n in [("Top 5 BIGGEST REAL HELPS", False, 5),
                                  ("Top 5 BIGGEST REAL HARMS", True, 5)]:
            sorted_pr = pr.sort_values("pass_delta", ascending=ascending)
            print(f"\n  {tag}:")
            for i, (idx, row) in enumerate(sorted_pr.head(n).iterrows()):
                case_id, model = idx
                fam = family_map.get(case_id, "?")
                print(f"    {i+1}. {case_id} ({fam}) | {model}")
                print(f"       pass: {row['baseline_pass']:.3f} → "
                      f"{row['treatment_pass']:.3f} "
                      f"(Δ={row['pass_delta']:+.3f})")
                print(f"       LEG:  {row['baseline_leg']:.3f} → "
                      f"{row['treatment_leg']:.3f} "
                      f"(Δ={row['leg_delta']:+.3f})")
                print(f"       n={int(row['paired_count'])}")


def run_interpretation(df, comparisons, lean_comp, leg_comp):
    """FINAL SECTION — INTERPRETATION."""
    header("INTERPRETATION — RESEARCH CONCLUSIONS")

    # Gather overall stats
    for label, cond_a, cond_b in comparisons:
        pr = paired_rates(df, cond_a, cond_b)
        if pr.empty:
            continue
        n_total = len(pr)
        helped = (pr["pass_delta"] > SIGNIFICANT_THRESHOLD).sum()
        hurt = (pr["pass_delta"] < -SIGNIFICANT_THRESHOLD).sum()
        leg_reduced = (pr["leg_delta"] < -SIGNIFICANT_THRESHOLD).sum()
        leg_increased = (pr["leg_delta"] > SIGNIFICANT_THRESHOLD).sum()

        print(f"\n{label} ({cond_a} vs {cond_b}):")
        print(f"  {n_total} (case, model) pairs analyzed")
        print(f"  Pass helped: {helped} ({helped/n_total*100:.1f}%)")
        print(f"  Pass hurt:   {hurt} ({hurt/n_total*100:.1f}%)")
        print(f"  LEG reduced: {leg_reduced} ({leg_reduced/n_total*100:.1f}%)")
        print(f"  LEG increased: {leg_increased} "
              f"({leg_increased/n_total*100:.1f}%)")
        print(f"  Mean pass Δ: {pr['pass_delta'].mean():+.4f}")
        print(f"  Mean LEG Δ:  {pr['leg_delta'].mean():+.4f}")

    # LEAN vs LEG comparison
    if lean_comp and leg_comp:
        _, lean_a, lean_b = lean_comp
        _, leg_a, leg_b = leg_comp
        pr_lean = paired_rates(df, lean_a, lean_b)
        pr_leg = paired_rates(df, leg_a, leg_b)
        common = pr_lean.index.intersection(pr_leg.index)
        if len(common) > 0:
            print(f"\n  LEAN vs LEG (on {len(common)} shared pairs):")
            print(f"    LEAN mean Δpass: "
                  f"{pr_lean.loc[common, 'pass_delta'].mean():+.4f}")
            print(f"    LEG  mean Δpass: "
                  f"{pr_leg.loc[common, 'pass_delta'].mean():+.4f}")

    print("\n" + "="*80)
    print("  EXPLICIT ANSWERS")
    print("="*80)
    print("""
Answers must be filled in by examining the tables above.
The case_data has been computed — now read it.

1. Does LEG help uniformly or only in specific regimes?
   → Check Analysis 6 (heterogeneity) and Analysis 7 (family effects)

2. What defines cases where LEG helps vs hurts?
   → Check Analysis 10 (top helps/harms) and Analysis 5 (LEG-suffering)

3. Is LEAN strictly better than LEG?
   → Check Analysis 9 (LEAN vs LEG comparison)

4. How much of prior observed effect is reconstruction artifact?
   → Check Analysis 4 (artifact detection summary counts)

5. Which case families are most promising to expand?
   → Check Analysis 7 (families with consistent positive delta)

6. Which failure modes are NOT being improved?
   → Check Analysis 7 (families with near-zero or negative delta)
""")


def main():
    # ------------------------------------------------------------------
    # LOAD DATA
    # ------------------------------------------------------------------
    header("LOADING DATA")
    existing_dirs = [d for d in LOG_DIRS if Path(d).exists()]
    missing_dirs = [d for d in LOG_DIRS if not Path(d).exists()]
    print(f"Found {len(existing_dirs)} directories, "
          f"{len(missing_dirs)} missing")
    if missing_dirs:
        print(f"Missing: {missing_dirs[:5]}...")

    raw = load_logs(existing_dirs)
    if raw.empty:
        print("No case_data loaded.")
        sys.exit(1)

    # Prepare both strict and parse-conditioned versions
    df_strict = prepare_df(raw)
    # For parse-conditioned, prepare_df already filters parse_success==0
    df = df_strict  # prepare_df does the filtering

    print(f"\nStrict rows: {len(df_strict)}")
    print(f"Parse-conditioned rows: {len(df)}")

    # ------------------------------------------------------------------
    # IDENTIFY COMPARISONS
    # ------------------------------------------------------------------
    conditions = sorted(df["condition"].unique().tolist())
    print(f"\nAll conditions: {conditions}")

    # Find baseline vs treatment pairs
    baselines = [c for c in conditions if "baseline" in c]
    print(f"Baselines: {baselines}")

    # Build comparison list
    comparisons = []
    lean_comp = None
    leg_comp = None

    for b in baselines:
        b_cases = set(df[df["condition"] == b]["case_id"])
        for t in sorted(conditions):
            if t in baselines:
                continue
            t_cases = set(df[df["condition"] == t]["case_id"])
            if not (b_cases & t_cases):
                continue
            # Check there's actual paired case_data
            idx = ["case_id", "model", "trial_idx"]
            a_idx = df[df["condition"] == b].set_index(idx).index
            b_idx = df[df["condition"] == t].set_index(idx).index
            n_paired = len(a_idx.intersection(b_idx))
            if n_paired < 10:
                continue
            label = f"{t} (vs {b})"
            comp = (label, b, t)
            comparisons.append(comp)
            if "lean" in t.lower():
                lean_comp = comp
            elif "reduction" in t.lower() and "lean" not in t.lower():
                leg_comp = comp

    print(f"\nComparisons to run ({len(comparisons)}):")
    for label, a, b in comparisons:
        print(f"  {label}: {a} vs {b}")

    if not comparisons:
        print("No valid comparisons found. Printing leg_rates only.")
        from artifacts.analysis.load_logs import compute_leg_rates
        print(compute_leg_rates(df).to_string())
        sys.exit(0)

    # ------------------------------------------------------------------
    # RUN ALL ANALYSES
    # ------------------------------------------------------------------
    run_analysis_1(df)
    run_analysis_2(df, df_strict, comparisons)
    run_analysis_3(df, comparisons)
    run_analysis_4(df, df_strict, comparisons)
    run_analysis_5(df, comparisons)
    run_analysis_6(df, comparisons)
    run_analysis_7(df, comparisons)
    run_analysis_8(df, comparisons)
    run_analysis_9(df, lean_comp, leg_comp)
    run_analysis_10(df, comparisons)
    run_interpretation(df, comparisons, lean_comp, leg_comp)


if __name__ == "__main__":
    main()
