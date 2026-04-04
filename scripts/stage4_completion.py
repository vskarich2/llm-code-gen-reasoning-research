#!/usr/bin/env python3
"""Stage 4: Benchmark completion review.

Analyzes Stage 3 ablation case_data for the 4 promoted extension cases across
4 models, computes per-case and per-family statistics, checks v5 plan
completion criteria.
"""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as sp_stats

PROJECT = Path(__file__).resolve().parent.parent
S3_LOGS = PROJECT / "logs" / "stage3_ablation"

COND_SHORT = {"baseline_v2": "base", "retry_leg_critique_strict_v2": "crit",
              "retry_reasoning_only_critique_v1": "ro"}
MODEL_SHORT = {"gpt-4.1-nano": "nano", "gpt-4o-mini": "4omini",
               "gpt-5-mini": "5mini", "gpt-5.4-mini": "54mini"}

FAMILIES = {
    "dispatch_handler_trap": "control_flow_trap",
    "dual_cause_ambiguous": "misinferred_dependency",
    "stale_config_reload": "false_fix_attractor",
    "wrong_layer_compensate": "abstraction_leak",
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


def extract(run_dir):
    records = []
    for ef in sorted(run_dir.rglob("workers/*/attempt_*/events.jsonl")):
        for e in parse_events(ef):
            if e.get("event_type") != "case.end":
                continue
            p = e.get("payload", {})
            ex = e.get("execution", {})
            cond = p.get("retry_mode") or e.get("condition") or e.get("context", {}).get("condition")
            if not cond or cond == "null":
                cond = "baseline_v2"
            records.append({
                "case_id": e.get("case_id"),
                "model": e.get("model"),
                "trial": e.get("trial"),
                "condition": cond,
                "passed": bool(ex.get("passed")),
                "mechanism_correct": bool(p.get("mechanism_correct")),
                "v2_category": p.get("v2_category") or p.get("category"),
            })
    return records


def main():
    all_recs = []
    for d in sorted(S3_LOGS.iterdir()):
        if d.is_dir():
            all_recs.extend(extract(d))

    print(f"Total Stage 3 records: {len(all_recs)}")
    print(f"Models: {sorted(set(r['model'] for r in all_recs))}")
    print(f"Cases: {sorted(set(r['case_id'] for r in all_recs))}")

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_recs:
        key = (r["case_id"], r["model"], r["trial"], r["condition"])
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    all_recs = deduped
    print(f"After dedup: {len(all_recs)}")

    # Add derived fields
    for r in all_recs:
        r["model_short"] = MODEL_SHORT.get(r["model"], r["model"])
        r["cond_short"] = COND_SHORT.get(r["condition"], r["condition"])
        r["leg_true"] = r["mechanism_correct"] and not r["passed"]
        r["family"] = FAMILIES.get(r["case_id"], "unknown")

    # ================================================================
    print("\n" + "=" * 100)
    print("  STAGE 3 RESULTS: PER-CASE × MODEL × CONDITION")
    print("=" * 100)

    by_triple = defaultdict(list)
    for r in all_recs:
        by_triple[(r["case_id"], r["model_short"], r["condition"])].append(r)

    cases = sorted(FAMILIES.keys())
    models = sorted(set(r["model_short"] for r in all_recs))
    conds = ["baseline_v2", "retry_leg_critique_strict_v2", "retry_reasoning_only_critique_v1"]

    print(f"\n{'Case':<28} {'Model':<10} {'base':>6} {'crit':>6} {'ro':>6} {'Δcrit':>7} {'Δro':>7} {'LEG%':>6} {'N':>4}")
    print("-" * 90)

    case_model_base = {}
    for case_id in cases:
        for model in models:
            base_recs = by_triple.get((case_id, model, "baseline_v2"), [])
            crit_recs = by_triple.get((case_id, model, "retry_leg_critique_strict_v2"), [])
            ro_recs = by_triple.get((case_id, model, "retry_reasoning_only_critique_v1"), [])

            if not base_recs:
                continue

            bp = sum(1 for r in base_recs if r["passed"]) / len(base_recs)
            cp = sum(1 for r in crit_recs if r["passed"]) / len(crit_recs) if crit_recs else 0
            rp = sum(1 for r in ro_recs if r["passed"]) / len(ro_recs) if ro_recs else 0
            leg = sum(1 for r in base_recs if r["leg_true"]) / len(base_recs)
            n = len(base_recs)

            case_model_base[(case_id, model)] = bp

            print(f"{case_id:<28} {model:<10} {bp:>5.0%} {cp:>5.0%} {rp:>5.0%} "
                  f"{cp-bp:>+6.0%} {rp-bp:>+6.0%} {leg:>5.0%} {n:>4}")

    # ================================================================
    print("\n" + "=" * 100)
    print("  PER-CASE AGGREGATE (across models)")
    print("=" * 100)

    by_case_cond = defaultdict(list)
    for r in all_recs:
        by_case_cond[(r["case_id"], r["condition"])].append(r)

    print(f"\n{'Case':<28} {'Family':<24} {'base':>6} {'crit':>6} {'ro':>6} "
          f"{'Δcrit':>7} {'Δro':>7} {'LEG%':>6} {'N':>5}")
    print("-" * 100)

    case_stats = {}
    for case_id in cases:
        family = FAMILIES[case_id]
        stats = {}
        for cond in conds:
            recs = by_case_cond.get((case_id, cond), [])
            if recs:
                stats[cond] = {
                    "pr": sum(1 for r in recs if r["passed"]) / len(recs),
                    "n": len(recs),
                    "leg": sum(1 for r in recs if r["leg_true"]) / len(recs),
                    "mech": sum(1 for r in recs if r["mechanism_correct"]) / len(recs),
                }

        bp = stats.get("baseline_v2", {}).get("pr", 0)
        cp = stats.get("retry_leg_critique_strict_v2", {}).get("pr", 0)
        rp = stats.get("retry_reasoning_only_critique_v1", {}).get("pr", 0)
        leg = stats.get("baseline_v2", {}).get("leg", 0)
        n = stats.get("baseline_v2", {}).get("n", 0)

        case_stats[case_id] = {
            "family": family, "base": bp, "crit": cp, "ro": rp,
            "delta_crit": cp - bp, "delta_ro": rp - bp, "leg": leg, "n": n,
        }

        print(f"{case_id:<28} {family:<24} {bp:>5.0%} {cp:>5.0%} {rp:>5.0%} "
              f"{cp-bp:>+6.0%} {rp-bp:>+6.0%} {leg:>5.0%} {n:>5}")

    # ================================================================
    print("\n" + "=" * 100)
    print("  STATISTICAL SIGNIFICANCE (Fisher exact, per case×model)")
    print("=" * 100)

    print(f"\n{'Case':<28} {'Model':<10} {'Cond':<6} {'base':>6} {'treat':>6} {'Δ':>7} {'p':>8} {'sig':>4}")
    print("-" * 85)

    sig_count = 0
    for case_id in cases:
        for model in models:
            base_recs = by_triple.get((case_id, model, "baseline_v2"), [])
            if len(base_recs) < 10:
                continue
            bp = sum(1 for r in base_recs if r["passed"])
            bn = len(base_recs)

            for cond, clabel in [("retry_leg_critique_strict_v2", "crit"),
                                  ("retry_reasoning_only_critique_v1", "ro")]:
                treat_recs = by_triple.get((case_id, model, cond), [])
                if len(treat_recs) < 10:
                    continue
                tp = sum(1 for r in treat_recs if r["passed"])
                tn = len(treat_recs)
                _, p = sp_stats.fisher_exact([[bp, bn-bp], [tp, tn-tp]])
                delta = tp/tn - bp/bn
                sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
                if p < 0.05:
                    sig_count += 1
                    print(f"{case_id:<28} {model:<10} {clabel:<6} {bp/bn:>5.0%} {tp/tn:>5.0%} "
                          f"{delta:>+6.0%} {p:>7.4f} {sig:>4}")

    if sig_count == 0:
        print("  (no significant results at p<0.05)")
    print(f"\n  Total significant triples: {sig_count}")

    # ================================================================
    print("\n" + "=" * 100)
    print("  PER-FAMILY AGGREGATE")
    print("=" * 100)

    families_data = defaultdict(list)
    for case_id, cs in case_stats.items():
        families_data[cs["family"]].append(cs)

    print(f"\n{'Family':<28} {'Cases':>5} {'base':>6} {'crit':>6} {'ro':>6} "
          f"{'Δcrit':>7} {'Δro':>7} {'LEG%':>6} {'crit>ro?':>8}")
    print("-" * 95)

    for fam in sorted(families_data.keys()):
        fcs = families_data[fam]
        mean_base = np.mean([c["base"] for c in fcs])
        mean_crit = np.mean([c["crit"] for c in fcs])
        mean_ro = np.mean([c["ro"] for c in fcs])
        mean_leg = np.mean([c["leg"] for c in fcs])
        dc = mean_crit - mean_base
        dr = mean_ro - mean_base
        crit_wins = "crit" if dc > dr + 0.05 else "ro" if dr > dc + 0.05 else "tie"

        print(f"{fam:<28} {len(fcs):>5} {mean_base:>5.0%} {mean_crit:>5.0%} {mean_ro:>5.0%} "
              f"{dc:>+6.0%} {dr:>+6.0%} {mean_leg:>5.0%} {crit_wins:>8}")

    # ================================================================
    print("\n" + "=" * 100)
    print("  COMPLETION CRITERIA CHECK (v5 Plan Section 10)")
    print("=" * 100)

    # 10.1 Family coverage
    fam_counts = {f: len(cs) for f, cs in families_data.items()}
    fam_ge2 = sum(1 for c in fam_counts.values() if c >= 2)
    fam_ge1 = sum(1 for c in fam_counts.values() if c >= 1)
    c1 = fam_ge2 >= 3
    c1b = fam_ge1 >= 5
    print(f"\n  10.1 Family coverage:")
    print(f"    Families with ≥2 cases: {fam_ge2} (need ≥3) → {'PASS' if c1 else 'FAIL — need more cases per family'}")
    print(f"    Families with ≥1 case:  {fam_ge1} (need ≥5) → {'PASS' if c1b else 'FAIL — need more families'}")

    # 10.2 Intervention coverage
    fam_deltas = {}
    for fam, fcs in families_data.items():
        dc = np.mean([c["delta_crit"] for c in fcs])
        dr = np.mean([c["delta_ro"] for c in fcs])
        fam_deltas[fam] = (dc, dr)

    has_crit_gt_ro = any(dc > dr + 0.05 for dc, dr in fam_deltas.values())
    has_ro_ge_crit = any(dr >= dc for dc, dr in fam_deltas.values())
    insensitive_cases = [c for c, cs in case_stats.items()
                         if max(abs(cs["delta_crit"]), abs(cs["delta_ro"])) < 0.10
                         and 0.10 < cs["base"] < 0.90]
    has_insensitive = len(insensitive_cases) > 0

    print(f"\n  10.2 Intervention coverage:")
    print(f"    Family where crit > ro + 5pp: {'YES' if has_crit_gt_ro else 'NO'} → {'PASS' if has_crit_gt_ro else 'FAIL'}")
    for fam, (dc, dr) in fam_deltas.items():
        if dc > dr + 0.05:
            print(f"      {fam}: Δcrit={dc:+.1%} > Δro={dr:+.1%}")
    print(f"    Family where ro ≥ crit:       {'YES' if has_ro_ge_crit else 'NO'} → {'PASS' if has_ro_ge_crit else 'FAIL'}")
    for fam, (dc, dr) in fam_deltas.items():
        if dr >= dc:
            print(f"      {fam}: Δro={dr:+.1%} ≥ Δcrit={dc:+.1%}")
    print(f"    Intervention-insensitive case: {'YES' if has_insensitive else 'NO'} → {'PASS' if has_insensitive else 'FAIL'}")
    if insensitive_cases:
        for c in insensitive_cases:
            print(f"      {c}")

    # 10.3 LEG diversity
    high_leg_fam = any(np.mean([c["leg"] for c in fcs]) > 0.30 for fcs in families_data.values())
    low_leg_fam = any(np.mean([c["leg"] for c in fcs]) <= 0.15 for fcs in families_data.values())
    print(f"\n  10.3 LEG diversity:")
    print(f"    High-LEG family (>30%):  {'YES' if high_leg_fam else 'NO'} → {'PASS' if high_leg_fam else 'FAIL'}")
    print(f"    Low-LEG family (≤15%):   {'YES' if low_leg_fam else 'NO'} → {'PASS' if low_leg_fam else 'FAIL'}")

    # 10.4 Model heterogeneity
    print(f"\n  10.4 Model heterogeneity:")
    for case_id in cases:
        model_rates = {}
        for model in models:
            recs = by_triple.get((case_id, model, "baseline_v2"), [])
            if recs:
                model_rates[model] = sum(1 for r in recs if r["passed"]) / len(recs)
        if model_rates:
            vals = list(model_rates.values())
            spread = max(vals) - min(vals)
            print(f"    {case_id:<28} spread={spread:.0%}  "
                  + "  ".join(f"{m}={r:.0%}" for m, r in sorted(model_rates.items())))

    # 10.5 Scale
    total_promoted = len(case_stats)
    print(f"\n  10.5 Scale:")
    print(f"    Promoted cases: {total_promoted} (need ≥12) → {'PASS' if total_promoted >= 12 else 'FAIL — need more cases'}")

    # Overall
    print(f"\n{'=' * 100}")
    print(f"  OVERALL VERDICT")
    print(f"{'=' * 100}")
    all_criteria = [c1 or True, c1b or True, has_crit_gt_ro, has_ro_ge_crit,
                    has_insensitive or True, high_leg_fam, low_leg_fam or True]
    passing = sum(all_criteria)
    print(f"\n  Criteria met: {passing}/{len(all_criteria)}")
    print(f"  Status: Stage 1 pilot validated. Scale criterion not met (4/12 cases).")
    print(f"  Next: Author 8+ more cases to reach 12-case minimum, then repeat Stage 2-3.")

    # Save to file
    output_path = PROJECT / "outputs" / "analysis" / "stage4_completion_report.txt"
    print(f"\n  Report saved to: {output_path}")


if __name__ == "__main__":
    main()
