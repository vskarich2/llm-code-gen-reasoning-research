#!/usr/bin/env python3
"""Per-case breakdown of all stats from global calibration analysis."""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS = PROJECT_ROOT / "logs"

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

CONDITION_SHORT = {
    "baseline_v2": "base",
    "retry_bare_retry_v2": "retry",
    "leg_reduction_lean_v2": "lean",
    "retry_leg_critique_strict_v2": "crit",
    "retry_reasoning_only_critique_v1": "ro",
    "leg_reduction_v2": "full",
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

CLUSTERS = {
    "Severe LEG": ["feature_flag_drift", "false_fix_deadlock"],
    "Moderate LEG": [
        "check_then_act", "overdetermination", "missing_branch_c",
        "hidden_dep_multihop", "config_shadowing", "invariant_partial_fail",
        "async_race_lock", "lost_update",
    ],
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
                "alignment_dim": payload.get("reasoning_code_alignment_dim"),
                "retry_passed_at": payload.get("retry_passed_at"),
            })
    return records


def load_all_data():
    all_records = []
    for log_subdir in sorted(LOGS.iterdir()):
        if not log_subdir.is_dir():
            continue
        name = log_subdir.name
        if not any(name.startswith(p) for p in INCLUDE_PREFIXES):
            continue
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
    df = pd.DataFrame(all_records)
    return df


def regime_classify(row, T=0.20):
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
        return "R-Only Dominant"
    if d_crit >= T and d_ro >= T and abs(d_crit - d_ro) < T:
        return "Interv-Equiv"
    return "No Effect"


def main():
    df = load_all_data()
    df["model_short"] = df["model"].map(MODEL_SHORT).fillna(df["model"])
    df["cond_short"] = df["condition"].map(CONDITION_SHORT).fillna(df["condition"])
    df = df.drop_duplicates(subset=["case_id", "model", "trial", "condition"])
    df["leg_true"] = df["mechanism_correct"] & ~df["passed"]
    df["cluster"] = df["case_id"].apply(get_cluster)

    cases = sorted(df["case_id"].unique())
    conds = ["baseline_v2", "retry_bare_retry_v2", "retry_leg_critique_strict_v2",
             "retry_reasoning_only_critique_v1", "leg_reduction_lean_v2", "leg_reduction_v2"]
    cond_labels = ["base", "retry", "crit", "ro", "lean", "full"]
    models = sorted(df["model_short"].unique())

    # ================================================================
    # PER-CASE SUMMARY TABLE
    # ================================================================
    print("=" * 120)
    print("  PER-CASE SUMMARY (across all models)")
    print("=" * 120)

    header = (f"{'Case':<30} {'Cluster':<16} "
              + "".join(f"{cl:>8}" for cl in cond_labels)
              + f" {'LEG%':>7} {'Mech%':>7} {'N_base':>7}")
    print(header)
    print("-" * len(header))

    case_summaries = []
    for case_id in cases:
        cdf = df[df["case_id"] == case_id]
        cluster = get_cluster(case_id)
        row_data = {"case_id": case_id, "cluster": cluster}

        parts = f"{case_id:<30} {cluster:<16} "
        for cond, cl in zip(conds, cond_labels):
            sub = cdf[cdf["condition"] == cond]
            if len(sub) > 0:
                pr = sub["passed"].mean()
                parts += f"{pr:>7.0%} "
                row_data[f"pass_{cl}"] = pr
            else:
                parts += f"{'—':>8}"
                row_data[f"pass_{cl}"] = np.nan

        base_sub = cdf[cdf["condition"] == "baseline_v2"]
        if len(base_sub) > 0:
            leg_r = base_sub["leg_true"].mean()
            mech_r = base_sub["mechanism_correct"].mean()
            n_base = len(base_sub)
            parts += f"{leg_r:>6.0%} {mech_r:>6.0%} {n_base:>7}"
            row_data["leg_rate"] = leg_r
            row_data["mech_rate"] = mech_r
            row_data["n_base"] = n_base
        else:
            parts += f"{'—':>7} {'—':>7} {'—':>7}"
            row_data["leg_rate"] = np.nan
            row_data["mech_rate"] = np.nan
            row_data["n_base"] = 0

        print(parts)
        case_summaries.append(row_data)

    # ================================================================
    # PER-CASE DELTAS (treatment - baseline)
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE DELTAS (treatment pass rate - baseline pass rate, across all models)")
    print(f"{'=' * 120}")

    treat_conds = [
        ("retry_bare_retry_v2", "Δretry"),
        ("retry_leg_critique_strict_v2", "Δcrit"),
        ("retry_reasoning_only_critique_v1", "Δro"),
        ("leg_reduction_lean_v2", "Δlean"),
        ("leg_reduction_v2", "Δfull"),
    ]

    header = (f"{'Case':<30} {'Cluster':<16} "
              + "".join(f"{label:>8}" for _, label in treat_conds)
              + f" {'best':>10}")
    print(header)
    print("-" * len(header))

    for cs in case_summaries:
        case_id = cs["case_id"]
        cluster = cs["cluster"]
        base_pr = cs.get("pass_base", np.nan)
        parts = f"{case_id:<30} {cluster:<16} "
        best_label = ""
        best_val = -999
        for cond, label in treat_conds:
            cl = CONDITION_SHORT[cond]
            treat_pr = cs.get(f"pass_{cl}", np.nan)
            if not np.isnan(base_pr) and not np.isnan(treat_pr):
                delta = treat_pr - base_pr
                parts += f"{delta:>+7.0%} "
                if delta > best_val:
                    best_val = delta
                    best_label = label
            else:
                parts += f"{'—':>8}"

        if best_val > 0.01:
            parts += f" {best_label:>10}"
        elif best_val > -999:
            parts += f" {'none':>10}"
        else:
            parts += f" {'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE × MODEL PASS RATE GRID
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE × MODEL: BASELINE PASS RATE")
    print(f"{'=' * 120}")

    header = f"{'Case':<30}" + "".join(f"{m:>10}" for m in models)
    print(header)
    print("-" * len(header))

    for case_id in cases:
        cdf = df[(df["case_id"] == case_id) & (df["condition"] == "baseline_v2")]
        parts = f"{case_id:<30}"
        for m in models:
            sub = cdf[cdf["model_short"] == m]
            if len(sub) > 0:
                parts += f"{sub['passed'].mean():>9.0%} "
            else:
                parts += f"{'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE × MODEL: CRITIQUE DELTA
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE × MODEL: Δ CRITIQUE (strict) vs BASELINE")
    print(f"{'=' * 120}")

    header = f"{'Case':<30}" + "".join(f"{m:>10}" for m in models)
    print(header)
    print("-" * len(header))

    pair_rates = df.groupby(
        ["case_id", "model_short", "condition"]
    )["passed"].mean().reset_index()

    for case_id in cases:
        parts = f"{case_id:<30}"
        for m in models:
            base_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "baseline_v2")
            ]["passed"].values
            crit_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "retry_leg_critique_strict_v2")
            ]["passed"].values
            if len(base_val) > 0 and len(crit_val) > 0:
                delta = crit_val[0] - base_val[0]
                parts += f"{delta:>+9.0%} "
            else:
                parts += f"{'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE × MODEL: REASONING-ONLY DELTA
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE × MODEL: Δ REASONING-ONLY vs BASELINE")
    print(f"{'=' * 120}")

    header = f"{'Case':<30}" + "".join(f"{m:>10}" for m in models)
    print(header)
    print("-" * len(header))

    for case_id in cases:
        parts = f"{case_id:<30}"
        for m in models:
            base_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "baseline_v2")
            ]["passed"].values
            ro_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "retry_reasoning_only_critique_v1")
            ]["passed"].values
            if len(base_val) > 0 and len(ro_val) > 0:
                delta = ro_val[0] - base_val[0]
                parts += f"{delta:>+9.0%} "
            else:
                parts += f"{'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE × MODEL: BARE RETRY DELTA
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE × MODEL: Δ BARE RETRY vs BASELINE")
    print(f"{'=' * 120}")

    header = f"{'Case':<30}" + "".join(f"{m:>10}" for m in models)
    print(header)
    print("-" * len(header))

    for case_id in cases:
        parts = f"{case_id:<30}"
        for m in models:
            base_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "baseline_v2")
            ]["passed"].values
            ret_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "retry_bare_retry_v2")
            ]["passed"].values
            if len(base_val) > 0 and len(ret_val) > 0:
                delta = ret_val[0] - base_val[0]
                parts += f"{delta:>+9.0%} "
            else:
                parts += f"{'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE × MODEL: LEG RATE (baseline)
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE × MODEL: BASELINE LEG RATE (mechanism correct & not passed)")
    print(f"{'=' * 120}")

    header = f"{'Case':<30}" + "".join(f"{m:>10}" for m in models)
    print(header)
    print("-" * len(header))

    for case_id in cases:
        cdf = df[(df["case_id"] == case_id) & (df["condition"] == "baseline_v2")]
        parts = f"{case_id:<30}"
        for m in models:
            sub = cdf[cdf["model_short"] == m]
            if len(sub) > 0:
                parts += f"{sub['leg_true'].mean():>9.0%} "
            else:
                parts += f"{'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE REGIME CLASSIFICATION (per model)
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE × MODEL: REGIME CLASSIFICATION")
    print(f"{'=' * 120}")

    regime_abbrev = {
        "Ceiling": "CEIL",
        "No Effect": "NONE",
        "Retry-Dominant": "RETRY",
        "Critique-Dominant": "CRIT",
        "R-Only Dominant": "RO",
        "Interv-Equiv": "EQUIV",
    }

    header = f"{'Case':<30}" + "".join(f"{m:>10}" for m in models)
    print(header)
    print("-" * len(header))

    for case_id in cases:
        parts = f"{case_id:<30}"
        for m in models:
            base_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "baseline_v2")
            ]["passed"].values
            retry_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "retry_bare_retry_v2")
            ]["passed"].values
            crit_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "retry_leg_critique_strict_v2")
            ]["passed"].values
            ro_val = pair_rates[
                (pair_rates["case_id"] == case_id)
                & (pair_rates["model_short"] == m)
                & (pair_rates["condition"] == "retry_reasoning_only_critique_v1")
            ]["passed"].values

            if len(base_val) > 0 and len(retry_val) > 0 and len(crit_val) > 0 and len(ro_val) > 0:
                row = {
                    "pass_base": base_val[0],
                    "delta_retry": retry_val[0] - base_val[0],
                    "delta_crit": crit_val[0] - base_val[0],
                    "delta_ro": ro_val[0] - base_val[0],
                }
                regime = regime_classify(row)
                abbr = regime_abbrev.get(regime, regime)
                parts += f"{abbr:>10}"
            else:
                parts += f"{'—':>10}"
        print(parts)

    # ================================================================
    # PER-CASE STATISTICAL SIGNIFICANCE (across models)
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE STATISTICAL TESTS (paired across models, treatment vs baseline)")
    print("  Shows Wilcoxon p-value where N>=5 model-level pairs exist")
    print(f"{'=' * 120}")

    header = (f"{'Case':<30} {'Cluster':<16} "
              f"{'Δcrit':>8} {'p_crit':>8} "
              f"{'Δro':>8} {'p_ro':>8} "
              f"{'Δretry':>8} {'p_retry':>8} "
              f"{'N':>4}")
    print(header)
    print("-" * len(header))

    for case_id in cases:
        cluster = get_cluster(case_id)
        parts = f"{case_id:<30} {cluster:<16} "

        # Get per-model pass rates for this case
        case_pairs = pair_rates[pair_rates["case_id"] == case_id]
        base_models = case_pairs[case_pairs["condition"] == "baseline_v2"][
            ["model_short", "passed"]
        ].rename(columns={"passed": "base"})

        for cond, label in [
            ("retry_leg_critique_strict_v2", "crit"),
            ("retry_reasoning_only_critique_v1", "ro"),
            ("retry_bare_retry_v2", "retry"),
        ]:
            treat_models = case_pairs[case_pairs["condition"] == cond][
                ["model_short", "passed"]
            ].rename(columns={"passed": "treat"})
            merged = base_models.merge(treat_models, on="model_short")
            if len(merged) >= 3:
                delta = (merged["treat"] - merged["base"]).mean()
                nonzero = merged["treat"] - merged["base"]
                nonzero = nonzero[nonzero != 0]
                if len(nonzero) >= 5:
                    _, p = stats.wilcoxon(nonzero)
                    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
                    parts += f"{delta:>+7.0%} {p:>6.3f}{sig:<2}"
                else:
                    parts += f"{delta:>+7.0%} {'n/a':>8}"
            else:
                parts += f"{'—':>8} {'—':>8}"

        n_models = len(base_models)
        parts += f" {n_models:>4}"
        print(parts)

    # ================================================================
    # PER-CASE v2 CATEGORY DISTRIBUTION (baseline only)
    # ================================================================
    print(f"\n{'=' * 120}")
    print("  PER-CASE OUTCOME CATEGORIES (baseline condition)")
    print(f"{'=' * 120}")

    cats = ["interpretable_success", "full_failure_v2", "LEG_v2",
            "alignment_failure_pass", "lucky_fix_v2", "parser_failure_v2"]
    cat_short = ["success", "fail", "LEG", "align_fail", "lucky", "parse_err"]

    header = f"{'Case':<30}" + "".join(f"{c:>12}" for c in cat_short) + f"{'N':>6}"
    print(header)
    print("-" * len(header))

    for case_id in cases:
        cdf = df[(df["case_id"] == case_id) & (df["condition"] == "baseline_v2")]
        if len(cdf) == 0:
            continue
        parts = f"{case_id:<30}"
        for cat in cats:
            rate = (cdf["v2_category"] == cat).mean()
            parts += f"{rate:>11.0%} "
        parts += f"{len(cdf):>5}"
        print(parts)

    print("\nDone.")


if __name__ == "__main__":
    main()
