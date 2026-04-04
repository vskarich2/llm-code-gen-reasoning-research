#!/usr/bin/env python3
"""Family-level intervention comparison.

For each case family, compare all 5 interventions:
- LEAN (single-shot)
- Full LEG (single-shot)
- Bare retry
- Retry + strict critique
- Retry + reasoning critique

Output: per-family table with mean Δpass, mean ΔLEG, % helped, % hurt,
help/harm ratio, and N.
"""

from pathlib import Path

import pandas as pd

from artifacts.analysis.load_logs import load_logs, prepare_df

pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 200)
pd.set_option("display.float_format", lambda x: f"{x:.3f}")

LOG_DIRS = [
    "logs/global_calibration/haiku45",
    "logs/global_calibration/sonnet46",
    "logs/global_calibration/nano",
    "logs/global_calibration/4omini",
    "logs/global_calibration/sonnet4",
    "logs/global_calibration/5mini",
    "logs/global_calibration/54mini",
    "logs/global_calibration/gpt5",
    "logs/retry_critique_stage0",
    "logs/retry_critique_stage0_anthropic",
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
    "logs/v2_anthropic_haiku45",
    "logs/v2_anthropic_sonnet46",
    "logs/v2_anthropic_sonnet46_v2",
    "logs/v2_anthropic_sonnet46_v3",
    "logs/v2_gpt5_50trial",
    "logs/v2_gpt5_50trial_v2",
    "logs/v2_full_4model_10trial_canonical",
    "logs/v2_targeted_50trial_canonical",
    "logs/v2_targeted_50trial_tranche2",
    "logs/v2_targeted_50trial_tranche3",
    "logs/v2_targeted_50trial_tranche4",
]

COMPARISONS = [
    ("LEAN", "baseline_v2", "leg_reduction_lean_v2"),
    ("Full LEG", "baseline_v2", "leg_reduction_v2"),
    ("Bare retry", "baseline_v2", "retry_bare_retry_v2"),
    ("Retry+strict", "baseline_v2", "retry_leg_critique_strict_v2"),
    ("Retry+reasoning", "baseline_v2", "retry_reasoning_only_critique_v1"),
]

SIG = 0.10  # significance threshold
LEG_THRESH = 0.40  # LEG-suffering threshold


def paired_case_model(df, cond_a, cond_b):
    """Paired deltas aggregated to (case_id, model) level."""
    idx = ["case_id", "model", "trial_idx"]
    keep = ["case_id", "model", "trial_idx", "pass", "leg_true",
            "reasoning_correct"]
    a = df[df["condition"] == cond_a][keep].set_index(idx)
    b = df[df["condition"] == cond_b][keep].set_index(idx)
    paired = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
    if len(paired) == 0:
        return pd.DataFrame()
    paired = paired.reset_index()
    paired["delta_pass"] = paired["pass_b"] - paired["pass_a"]
    paired["delta_leg"] = paired["leg_true_b"] - paired["leg_true_a"]
    g = paired.groupby(["case_id", "model"])
    return pd.DataFrame({
        "pass_delta": g["delta_pass"].mean(),
        "leg_delta": g["delta_leg"].mean(),
        "baseline_pass": g["pass_a"].mean(),
        "baseline_leg": g["leg_true_a"].mean(),
        "n": g["delta_pass"].count(),
    })


def family_stats(cm, family_map):
    """Aggregate (case_id, model)-level deltas to family level."""
    cm = cm.copy()
    cm["family"] = cm.index.get_level_values("case_id").map(family_map)
    records = []
    for fam, grp in cm.groupby("family"):
        n_pairs = len(grp)
        n_helped = (grp["pass_delta"] > SIG).sum()
        n_hurt = (grp["pass_delta"] < -SIG).sum()
        # LEG-suffering subset
        leg_suf = grp[grp["baseline_leg"] >= LEG_THRESH]
        n_leg_suf = len(leg_suf)
        leg_suf_improved = (leg_suf["pass_delta"] > SIG).sum() if n_leg_suf > 0 else 0
        leg_suf_worsened = (leg_suf["pass_delta"] < -SIG).sum() if n_leg_suf > 0 else 0
        records.append({
            "family": fam,
            "mean_dpass": grp["pass_delta"].mean(),
            "mean_dleg": grp["leg_delta"].mean(),
            "n_pairs": n_pairs,
            "n_helped": int(n_helped),
            "n_hurt": int(n_hurt),
            "help_harm": (
                n_helped / n_hurt if n_hurt > 0
                else (float("inf") if n_helped > 0 else 0.0)
            ),
            "n_leg_suffering": int(n_leg_suf),
            "leg_suf_improved": int(leg_suf_improved),
            "leg_suf_worsened": int(leg_suf_worsened),
        })
    return pd.DataFrame(records).set_index("family")


def main():
    existing = [d for d in LOG_DIRS if Path(d).exists()]
    raw = load_logs(existing)
    df = prepare_df(raw)

    family_map = df[["case_id", "family"]].drop_duplicates().set_index(
        "case_id")["family"]
    families = sorted(family_map.unique())

    # Compute per-family stats for each intervention
    intervention_data = {}
    for label, cond_a, cond_b in COMPARISONS:
        cm = paired_case_model(df, cond_a, cond_b)
        if cm.empty:
            continue
        intervention_data[label] = family_stats(cm, family_map)

    # ---- TABLE 1: Per-family intervention comparison ----
    print("=" * 160)
    print("  TABLE 1: FAMILY × INTERVENTION — Mean Δpass")
    print("=" * 160)
    dpass_table = pd.DataFrame({
        label: data["mean_dpass"]
        for label, data in intervention_data.items()
    })
    dpass_table = dpass_table.reindex(families)
    # Add a "best" column
    dpass_table["best_intervention"] = dpass_table[
        [c for c in dpass_table.columns]].idxmax(axis=1)
    print(dpass_table.to_string())

    # ---- TABLE 2: Per-family intervention comparison — Mean ΔLEG ----
    print("\n" + "=" * 160)
    print("  TABLE 2: FAMILY × INTERVENTION — Mean ΔLEG")
    print("=" * 160)
    dleg_table = pd.DataFrame({
        label: data["mean_dleg"]
        for label, data in intervention_data.items()
    })
    dleg_table = dleg_table.reindex(families)
    dleg_table["best_leg_reduction"] = dleg_table[
        [c for c in dleg_table.columns]].idxmin(axis=1)
    print(dleg_table.to_string())

    # ---- TABLE 3: Per-family help/harm ratio ----
    print("\n" + "=" * 160)
    print("  TABLE 3: FAMILY × INTERVENTION — Help/Harm Ratio "
          "(>10pp helped / >10pp hurt)")
    print("=" * 160)
    hh_records = []
    for fam in families:
        row = {"family": fam}
        for label, data in intervention_data.items():
            if fam in data.index:
                r = data.loc[fam]
                h = int(r["n_helped"])
                hr = int(r["n_hurt"])
                row[label] = f"{h}h/{hr}hr" if hr > 0 else f"{h}h/0hr"
            else:
                row[label] = "-"
        hh_records.append(row)
    hh_df = pd.DataFrame(hh_records).set_index("family")
    print(hh_df.to_string())

    # ---- TABLE 4: LEG-suffering conversion by family ----
    print("\n" + "=" * 160)
    print("  TABLE 4: LEG-SUFFERING PAIRS BY FAMILY — "
          "How many (case,model) pairs with baseline LEG ≥ 0.4 "
          "are improved >10pp?")
    print("=" * 160)
    leg_records = []
    for fam in families:
        row = {"family": fam}
        for label, data in intervention_data.items():
            if fam in data.index:
                r = data.loc[fam]
                n = int(r["n_leg_suffering"])
                imp = int(r["leg_suf_improved"])
                worse = int(r["leg_suf_worsened"])
                if n > 0:
                    row[label] = f"{imp}/{n} imp, {worse}/{n} worse"
                else:
                    row[label] = "no LEG"
            else:
                row[label] = "-"
        leg_records.append(row)
    leg_df = pd.DataFrame(leg_records).set_index("family")
    print(leg_df.to_string())

    # ---- TABLE 5: Families ranked by best intervention Δpass ----
    print("\n" + "=" * 160)
    print("  TABLE 5: FAMILIES RANKED BY BEST ACHIEVABLE Δpass")
    print("=" * 160)
    best_dpass = dpass_table.drop(columns=["best_intervention"]).max(axis=1)
    best_which = dpass_table["best_intervention"]
    ranked = pd.DataFrame({
        "best_dpass": best_dpass,
        "best_intervention": best_which,
        "worst_dpass": dpass_table.drop(
            columns=["best_intervention"]).min(axis=1),
        "spread": best_dpass - dpass_table.drop(
            columns=["best_intervention"]).min(axis=1),
    }).sort_values("best_dpass", ascending=False)
    print(ranked.to_string())

    # ---- TABLE 6: Intervention-resistant families ----
    print("\n" + "=" * 160)
    print("  TABLE 6: INTERVENTION-RESISTANT FAMILIES "
          "(best Δpass < +5pp across ALL interventions)")
    print("=" * 160)
    resistant = ranked[ranked["best_dpass"] < 0.05]
    if len(resistant) > 0:
        print(resistant.to_string())
    else:
        print("None — all families respond to at least one intervention")

    # ---- Summary ----
    print("\n" + "=" * 160)
    print("  SUMMARY: WHICH INTERVENTION WINS PER FAMILY?")
    print("=" * 160)
    wins = dpass_table["best_intervention"].value_counts()
    print(wins.to_string())
    print(f"\nTotal families: {len(families)}")


if __name__ == "__main__":
    main()
