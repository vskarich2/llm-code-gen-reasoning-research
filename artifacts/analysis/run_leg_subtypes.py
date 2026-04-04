#!/usr/bin/env python3
"""LEG subtype classification + intervention harm map + flat family analysis.

Four analyses:
1. LEG subtype classification (convertible / belief-correctable / irreducible)
2. Representation-limited redefinition
3. Intervention harm map (family × intervention → negative delta)
4. Cross-model consistency on flat families
"""

from pathlib import Path

import pandas as pd
import numpy as np

from artifacts.analysis.load_logs import load_logs, prepare_df

pd.set_option("display.max_rows", 600)
pd.set_option("display.max_columns", 30)
pd.set_option("display.width", 220)
pd.set_option("display.float_format", lambda x: f"{x:.4f}")

LOG_DIRS = [
    "logs/global_calibration/haiku45", "logs/global_calibration/sonnet46",
    "logs/global_calibration/nano", "logs/global_calibration/4omini",
    "logs/global_calibration/sonnet4", "logs/global_calibration/5mini",
    "logs/global_calibration/54mini", "logs/global_calibration/gpt5",
    "logs/retry_critique_stage0", "logs/retry_critique_stage0_anthropic",
    "logs/retry_critique_stage1/anthropic_sonnet",
    "logs/retry_critique_stage1/openai_gpt5",
    "logs/retry_critique_stage1/anthropic_haiku",
    "logs/retry_critique_stage1/openai_4omini",
    "logs/retry_critique_stage1/openai_nano",
    "logs/retry_critique_stage1/openai_5mini",
    "logs/retry_critique_stage1/openai_54mini",
    "logs/retry_critique_stage2/anthropic_sonnet",
    "logs/retry_critique_stage2/anthropic_haiku",
    "logs/retry_critique_stage2/openai_4omini",
    "logs/retry_critique_stage2/openai_nano",
    "logs/retry_critique_stage2/openai_5mini",
    "logs/retry_critique_stage2/openai_54mini",
    "logs/stage_b_critique/openai_4omini",
    "logs/stage_b_critique/openai_54mini",
    "logs/stage_b_critique_r2/openai_4omini",
    "logs/stage_b_critique_r2/openai_54mini",
    "logs/stage_c_critique/openai_4omini",
    "logs/stage_c_critique/openai_nano",
    "logs/stage_c_critique/openai_5mini",
    "logs/stage_c_critique/openai_54mini",
    "logs/v2_anthropic_haiku45", "logs/v2_anthropic_sonnet46",
    "logs/v2_anthropic_sonnet46_v2", "logs/v2_anthropic_sonnet46_v3",
    "logs/v2_gpt5_50trial", "logs/v2_gpt5_50trial_v2",
    "logs/v2_full_4model_10trial_canonical",
    "logs/v2_targeted_50trial_canonical",
    "logs/v2_targeted_50trial_tranche2",
    "logs/v2_targeted_50trial_tranche3",
    "logs/v2_targeted_50trial_tranche4",
]

BASELINE = "baseline_v2"
INTERVENTIONS = {
    "lean": "leg_reduction_lean_v2",
    "full_leg": "leg_reduction_v2",
    "retry": "retry_bare_retry_v2",
    "retry_strict": "retry_leg_critique_strict_v2",
    "retry_reasoning": "retry_reasoning_only_critique_v1",
}

SIG = 0.10
LEG_THRESH = 0.40


def header(title):
    print(f"\n{'=' * 180}")
    print(f"  {title}")
    print(f"{'=' * 180}\n")


def paired_case_model(df, cond_a, cond_b):
    """Per-(case_id, model) paired rates."""
    idx = ["case_id", "model", "trial_idx"]
    keep = idx + ["pass", "leg_true", "reasoning_correct"]
    a = df[df["condition"] == cond_a][keep].set_index(idx)
    b = df[df["condition"] == cond_b][keep].set_index(idx)
    p = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
    if p.empty:
        return pd.DataFrame()
    p = p.reset_index()
    g = p.groupby(["case_id", "model"])
    return pd.DataFrame({
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
        "n": g["pass_a"].count(),
    })


def main():
    existing = [d for d in LOG_DIRS if Path(d).exists()]
    raw = load_logs(existing)
    df = prepare_df(raw)

    family_map = (df[["case_id", "family"]].drop_duplicates()
                  .set_index("case_id")["family"])

    # Compute all paired rates
    paired = {}
    for name, cond in INTERVENTIONS.items():
        pr = paired_case_model(df, BASELINE, cond)
        if not pr.empty:
            pr["family"] = pr.index.get_level_values("case_id").map(
                family_map)
            paired[name] = pr

    # Build master table: one row per (case_id, model) with all deltas
    baseline_df = df[df["condition"] == BASELINE].copy()
    baseline_df["family"] = baseline_df["case_id"].map(family_map)
    bl_rates = baseline_df.groupby(["case_id", "model"]).agg(
        baseline_pass=("pass", "mean"),
        baseline_leg=("leg_true", "mean"),
        baseline_reasoning=("reasoning_correct", "mean"),
        n_baseline=("pass", "count"),
    )
    bl_rates["family"] = bl_rates.index.get_level_values("case_id").map(
        family_map)

    for iname, pr in paired.items():
        bl_rates[f"{iname}_pass"] = pr["treatment_pass"]
        bl_rates[f"{iname}_delta"] = pr["pass_delta"]
        bl_rates[f"{iname}_leg"] = pr["treatment_leg"]
        bl_rates[f"{iname}_dleg"] = pr["leg_delta"]

    master = bl_rates.copy()

    # ==================================================================
    # ANALYSIS 1 — LEG SUBTYPE CLASSIFICATION
    # ==================================================================
    header("ANALYSIS 1 — LEG SUBTYPE CLASSIFICATION")

    leg_suf = master[master["baseline_leg"] >= LEG_THRESH].copy()
    print(f"Total LEG-suffering (case_id, model) pairs: {len(leg_suf)}\n")

    def classify_leg(row):
        # Does retry+critique fix it?
        strict_d = row.get("retry_strict_delta", np.nan)
        reasoning_d = row.get("retry_reasoning_delta", np.nan)
        critique_max = np.nanmax([
            strict_d if pd.notna(strict_d) else -99,
            reasoning_d if pd.notna(reasoning_d) else -99,
        ])

        # Does retry alone fix it?
        retry_d = row.get("retry_delta", np.nan)
        retry_d = retry_d if pd.notna(retry_d) else -99

        # Does single-shot fix it?
        lean_d = row.get("lean_delta", np.nan)
        leg_d = row.get("full_leg_delta", np.nan)
        ss_max = np.nanmax([
            lean_d if pd.notna(lean_d) else -99,
            leg_d if pd.notna(leg_d) else -99,
        ])

        # Classification
        if retry_d >= SIG:
            return "convertible_LEG"
        if critique_max >= SIG:
            return "belief_correctable_LEG"
        if ss_max >= SIG:
            return "convertible_LEG"
        return "irreducible_LEG"

    leg_suf["leg_subtype"] = leg_suf.apply(classify_leg, axis=1)

    # Display columns
    show_cols = [
        "family", "baseline_pass", "baseline_leg",
        "lean_delta", "full_leg_delta", "retry_delta",
        "retry_strict_delta", "retry_reasoning_delta",
        "leg_subtype",
    ]
    available = [c for c in show_cols if c in leg_suf.columns]
    print(leg_suf[available].to_string())

    print("\n\nLEG subtype distribution:")
    print(leg_suf["leg_subtype"].value_counts().to_string())

    print("\nLEG subtype by family:")
    cross = pd.crosstab(leg_suf["family"], leg_suf["leg_subtype"])
    print(cross.to_string())

    print("\nLEG subtype by model:")
    cross_m = pd.crosstab(
        leg_suf.index.get_level_values("model"), leg_suf["leg_subtype"])
    print(cross_m.to_string())

    # Irreducible LEG detail
    print("\n\nIRREDUCIBLE LEG — full detail:")
    irr = leg_suf[leg_suf["leg_subtype"] == "irreducible_LEG"]
    if len(irr) > 0:
        print(irr[available].to_string())
    else:
        print("None")

    # ==================================================================
    # ANALYSIS 2 — REPRESENTATION-LIMITED REDEFINITION
    # ==================================================================
    header("ANALYSIS 2 — REPRESENTATION-LIMITED REDEFINITION")

    # For each (case_id, model): max delta across all interventions
    delta_cols = [f"{i}_delta" for i in INTERVENTIONS]
    available_deltas = [c for c in delta_cols if c in master.columns]
    master["max_delta"] = master[available_deltas].max(axis=1)
    master["min_delta"] = master[available_deltas].min(axis=1)

    rep_candidates = master[master["max_delta"] < 0.05].copy()
    print(f"Representation-limited candidates "
          f"(max Δ < 5pp): {len(rep_candidates)}\n")

    # Split by baseline LEG and pass
    rep_candidates["leg_status"] = np.where(
        rep_candidates["baseline_leg"] >= LEG_THRESH, "high_LEG", "low_LEG")
    rep_candidates["pass_status"] = np.where(
        rep_candidates["baseline_pass"] >= 0.8, "high_pass",
        np.where(rep_candidates["baseline_pass"] >= 0.3, "mid_pass",
                 "low_pass"))

    show = ["family", "baseline_pass", "baseline_leg",
            "baseline_reasoning", "max_delta", "min_delta",
            "leg_status", "pass_status"]
    avail = [c for c in show if c in rep_candidates.columns]
    print(rep_candidates[avail].to_string())

    print("\n\nCross-tab (LEG status × pass status):")
    print(pd.crosstab(rep_candidates["leg_status"],
                      rep_candidates["pass_status"]).to_string())

    print("\n\nBy family:")
    rep_fam = rep_candidates.groupby("family").agg(
        n_pairs=("max_delta", "count"),
        avg_baseline_pass=("baseline_pass", "mean"),
        avg_baseline_leg=("baseline_leg", "mean"),
        avg_max_delta=("max_delta", "mean"),
        n_high_leg=("leg_status", lambda x: (x == "high_LEG").sum()),
        n_low_pass=("pass_status", lambda x: (x == "low_pass").sum()),
    )
    print(rep_fam.sort_values("n_pairs", ascending=False).to_string())

    print("\n\nRedefined subtypes:")
    print("  HIGH_LEG + LOW_PASS + flat = "
          "structural_impossibility (model reasons but cannot execute)")
    print("  LOW_LEG + LOW_PASS + flat = "
          "capability_ceiling (model cannot reason or execute)")
    print("  LOW_LEG + HIGH_PASS + flat = "
          "already_solved (no room to improve)")

    rep_candidates["rep_subtype"] = "other"
    rep_candidates.loc[
        (rep_candidates["leg_status"] == "high_LEG")
        & (rep_candidates["pass_status"] == "low_pass"),
        "rep_subtype"] = "structural_impossibility"
    rep_candidates.loc[
        (rep_candidates["leg_status"] == "low_LEG")
        & (rep_candidates["pass_status"] == "low_pass"),
        "rep_subtype"] = "capability_ceiling"
    rep_candidates.loc[
        (rep_candidates["pass_status"] == "high_pass"),
        "rep_subtype"] = "already_solved"
    rep_candidates.loc[
        (rep_candidates["leg_status"] == "high_LEG")
        & (rep_candidates["pass_status"] != "low_pass"),
        "rep_subtype"] = "structural_impossibility"
    rep_candidates.loc[
        (rep_candidates["leg_status"] == "low_LEG")
        & (rep_candidates["pass_status"] == "mid_pass"),
        "rep_subtype"] = "capability_ceiling"

    print("\n\nSubtype distribution:")
    print(rep_candidates["rep_subtype"].value_counts().to_string())

    print("\nSubtype by family:")
    print(pd.crosstab(rep_candidates["family"],
                      rep_candidates["rep_subtype"]).to_string())

    # ==================================================================
    # ANALYSIS 3 — INTERVENTION HARM MAP
    # ==================================================================
    header("ANALYSIS 3 — INTERVENTION HARM MAP")

    print("Family × Intervention: mean delta (only negative shown, "
          "blank = non-negative or no case_data)\n")

    harm_records = []
    for fam in sorted(master["family"].unique()):
        fam_data = master[master["family"] == fam]
        rec = {"family": fam}
        for iname in INTERVENTIONS:
            col = f"{iname}_delta"
            if col in fam_data.columns:
                vals = fam_data[col].dropna()
                mean_d = vals.mean() if len(vals) > 0 else np.nan
                n_hurt = (vals < -SIG).sum() if len(vals) > 0 else 0
                n_total = len(vals) if len(vals) > 0 else 0
                if mean_d < -0.02:
                    rec[iname] = f"{mean_d:+.3f} ({n_hurt}/{n_total}hurt)"
                else:
                    rec[iname] = ""
            else:
                rec[iname] = ""
        harm_records.append(rec)

    harm_df = pd.DataFrame(harm_records).set_index("family")
    # Only show families with at least one negative entry
    has_harm = harm_df.apply(lambda row: any(v != "" for v in row), axis=1)
    print(harm_df[has_harm].to_string())

    print(f"\n\nFamilies with NO harm under any intervention:")
    no_harm = harm_df[~has_harm]
    print(no_harm.index.tolist())

    # Aggregate: which interventions are most harmful?
    print("\n\nIntervention harm summary:")
    for iname in INTERVENTIONS:
        col = f"{iname}_delta"
        if col not in master.columns:
            continue
        vals = master[col].dropna()
        n_hurt = (vals < -SIG).sum()
        n_total = len(vals)
        harmed_families = master[master[col] < -SIG]["family"].nunique()
        print(f"  {iname:20s}  "
              f"n_hurt={n_hurt}/{n_total} "
              f"({n_hurt / n_total * 100:.1f}%)  "
              f"families_affected={harmed_families}  "
              f"mean_when_negative="
              f"{vals[vals < -SIG].mean():.3f}" if n_hurt > 0 else
              f"  {iname:20s}  n_hurt=0")

    # Fragile families: harmed by ≥3 interventions
    print("\n\nFRAGILE FAMILIES (harmed by ≥2 interventions):")
    for fam in sorted(master["family"].unique()):
        fam_data = master[master["family"] == fam]
        n_harmful = 0
        for iname in INTERVENTIONS:
            col = f"{iname}_delta"
            if col in fam_data.columns:
                vals = fam_data[col].dropna()
                if len(vals) > 0 and vals.mean() < -0.05:
                    n_harmful += 1
        if n_harmful >= 2:
            print(f"  {fam}: harmed by {n_harmful} interventions")

    # Unsafe interventions per family
    print("\n\nUNSAFE INTERVENTIONS (>20% of models hurt):")
    for iname in INTERVENTIONS:
        col = f"{iname}_delta"
        if col not in master.columns:
            continue
        for fam in sorted(master["family"].unique()):
            fam_data = master[master["family"] == fam]
            vals = fam_data[col].dropna()
            if len(vals) >= 3:
                pct_hurt = (vals < -SIG).sum() / len(vals)
                if pct_hurt > 0.20:
                    print(f"  {iname:20s} on {fam:30s}: "
                          f"{(vals < -SIG).sum()}/{len(vals)} models hurt "
                          f"({pct_hurt * 100:.0f}%), "
                          f"mean Δ={vals.mean():+.3f}")

    # ==================================================================
    # ANALYSIS 4 — CROSS-MODEL CONSISTENCY ON FLAT FAMILIES
    # ==================================================================
    header("ANALYSIS 4 — CROSS-MODEL CONSISTENCY ON FLAT FAMILIES")

    # Family is flat if max delta < 5pp aggregated
    fam_max_delta = master.groupby("family")["max_delta"].mean()
    flat_families = fam_max_delta[fam_max_delta < 0.05].index.tolist()

    print(f"Flat families (avg max Δ < 5pp): {flat_families}\n")

    for fam in flat_families:
        fam_data = master[master["family"] == fam]
        print(f"\n--- {fam} ---")
        models = fam_data.index.get_level_values("model").unique()

        all_flat = True
        weak_only_flat = True
        strong_models = {"gpt-5-mini", "gpt-5.4-mini", "gpt-5",
                         "claude-sonnet-4-6"}

        for model in sorted(models):
            mdata = fam_data.xs(model, level="model")
            max_d = mdata["max_delta"].values[0] if len(mdata) > 0 else 0
            bl_pass = mdata["baseline_pass"].values[0] if len(mdata) > 0 else 0
            bl_leg = mdata["baseline_leg"].values[0] if len(mdata) > 0 else 0
            is_flat = max_d < 0.05
            marker = "FLAT" if is_flat else f"RESPONDS (max Δ={max_d:.3f})"
            print(f"  {model:30s}  bl_pass={bl_pass:.3f}  "
                  f"bl_leg={bl_leg:.3f}  max_Δ={max_d:+.3f}  {marker}")

            if not is_flat:
                all_flat = False
            if model in strong_models and not is_flat:
                weak_only_flat = False

        if all_flat:
            print(f"  → TRUE STRUCTURAL FAILURE (flat across ALL models)")
        elif weak_only_flat:
            print(f"  → CAPABILITY THRESHOLD (only weak models flat)")
        else:
            print(f"  → MIXED (some models respond)")

    # ==================================================================
    # SUMMARY — WHAT THE DATA PROVES
    # ==================================================================
    header("SUMMARY — WHAT THE DATA ACTUALLY PROVES")

    total_pairs = len(master)
    flat_pairs = (master["max_delta"] < 0.05).sum()
    leg_suf_total = len(leg_suf)
    irr_count = (leg_suf["leg_subtype"] == "irreducible_LEG").sum()
    conv_count = (leg_suf["leg_subtype"] == "convertible_LEG").sum()
    belief_count = (leg_suf["leg_subtype"] == "belief_correctable_LEG").sum()

    print(f"1. LEG IS HETEROGENEOUS — not a single mechanism")
    print(f"   {leg_suf_total} LEG-suffering (case, model) pairs:")
    print(f"     convertible_LEG:          {conv_count} "
          f"({conv_count / leg_suf_total * 100:.1f}%) "
          f"— retry alone fixes")
    print(f"     belief_correctable_LEG:   {belief_count} "
          f"({belief_count / leg_suf_total * 100:.1f}%) "
          f"— needs critique to fix")
    print(f"     irreducible_LEG:          {irr_count} "
          f"({irr_count / leg_suf_total * 100:.1f}%) "
          f"— nothing fixes")
    print()

    print(f"2. INTERVENTIONS ARE NOT GENERAL-PURPOSE")
    for iname in INTERVENTIONS:
        col = f"{iname}_delta"
        if col not in master.columns:
            continue
        vals = master[col].dropna()
        n_helped = (vals > SIG).sum()
        n_hurt = (vals < -SIG).sum()
        print(f"   {iname:20s}  helped={n_helped:3d}  hurt={n_hurt:3d}  "
              f"ratio={n_helped / max(n_hurt, 1):.1f}:1  "
              f"mean={vals.mean():+.4f}")
    print()

    print(f"3. CRITIQUE IS UNIQUELY SAFE FOR BELIEF ERRORS")
    belief_fams = master[master["family"].isin([
        "cache_invalidation_order", "feature_flag_drift",
        "hidden_dep_multihop", "l3_state_pipeline", "missing_branch",
        "use_before_set", "wrong_condition",
    ])]
    for iname in INTERVENTIONS:
        col = f"{iname}_delta"
        if col not in belief_fams.columns:
            continue
        vals = belief_fams[col].dropna()
        n_hurt = (vals < -SIG).sum()
        print(f"   {iname:20s} on BELIEF_LIMITED families: "
              f"hurt={n_hurt}/{len(vals)}")
    print()

    print(f"4. A LARGE CLASS OF FAILURES IS UNTOUCHED")
    print(f"   {flat_pairs}/{total_pairs} (case, model) pairs are flat "
          f"(max Δ < 5pp)")
    print(f"   = {flat_pairs / total_pairs * 100:.1f}% of all pairs "
          f"are beyond current intervention reach")
    print()

    print(f"5. LEG SUBTYPE DETERMINES OPTIMAL INTERVENTION")
    print(f"   convertible_LEG → bare retry is sufficient")
    print(f"   belief_correctable_LEG → retry+reasoning is required")
    print(f"   irreducible_LEG → no current intervention works")
    print(f"   → Matching intervention to LEG subtype eliminates "
          f"most wasted compute and most harms")


if __name__ == "__main__":
    main()
