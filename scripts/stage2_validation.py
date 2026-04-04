#!/usr/bin/env python3
"""Stage 2 validation for benchmark extension cases.

Checks all v5 plan Stage 2 gates:
1. Observed failure pattern (≥50% match)
2. Trap activation (≥20% of failures)
3. Intervention probe (delta ≥10pp → intervention-sensitive)
4. Floor/ceiling (not 0% or ≥90% baseline)
"""

import json
from collections import defaultdict
from pathlib import Path

from scipy import stats as sp_stats

PROJECT = Path(__file__).resolve().parent.parent
LOGS = PROJECT / "logs" / "stage2_calibration"

CASE_META = {
    "cache_bypass_attractor": {
        "family": "false_fix_attractor",
        "root_cause_file": "cache_manager",
        "attractor_files": ["report_generator", "data_store"],
    },
    "dispatch_handler_trap": {
        "family": "control_flow_trap",
        "root_cause_file": "dispatcher",
        "attractor_files": ["handlers"],
    },
    "wrong_layer_compensate": {
        "family": "abstraction_leak",
        "root_cause_file": "parser",
        "attractor_files": ["formatter"],
    },
    "dual_cause_ambiguous": {
        "family": "misinferred_dependency",
        "root_cause_file": "data_loader",
        "attractor_files": ["aggregator", "report"],
    },
    "stale_config_reload": {
        "family": "false_fix_attractor",
        "root_cause_file": "config_loader",
        "attractor_files": ["validator", "app"],
    },
    "incomplete_state_sync": {
        "family": "intervention_boundary",
        "root_cause_file": "profile",
        "attractor_files": ["search_index"],
    },
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


def extract_records(run_dir):
    records = []
    for ef in sorted(run_dir.rglob("workers/*/attempt_*/events.jsonl")):
        for e in parse_events(ef):
            if e.get("event_type") != "case.end":
                continue
            p = e.get("payload", {})
            ex = e.get("execution", {})
            cond = (
                p.get("retry_mode")
                or e.get("condition")
                or e.get("context", {}).get("condition")
            )
            if not cond or cond == "null":
                cond = "baseline_v2"

            # Extract which file the model's code targeted
            code = p.get("_extracted_code", "") or ""
            assembled = p.get("_assembled_code", "")

            records.append({
                "case_id": e.get("case_id"),
                "model": e.get("model"),
                "trial": e.get("trial"),
                "condition": cond,
                "passed": bool(ex.get("passed")),
                "mechanism_correct": bool(p.get("mechanism_correct")),
                "v2_category": p.get("v2_category") or p.get("category"),
                "code_snippet": code[:500] if code else "",
            })
    return records


def classify_failure(rec, meta):
    """Classify a failed attempt by which file it appears to target."""
    code = rec.get("code_snippet", "").lower()
    root = meta["root_cause_file"].lower()
    attractors = [a.lower() for a in meta["attractor_files"]]

    # Check for mentions of root cause file's functions
    if root in code or f"def {root}" in code:
        return "true_fix_direction"

    for a in attractors:
        if a in code or f"def {a}" in code:
            return "attractor_chosen"

    return "unrelated"


def main():
    all_records = []
    for model_dir in sorted(LOGS.iterdir()):
        if not model_dir.is_dir():
            continue
        recs = extract_records(model_dir)
        all_records.extend(recs)

    if not all_records:
        print("ERROR: No records found")
        return

    print(f"Total records: {len(all_records)}")
    print(f"Models: {sorted(set(r['model'] for r in all_records))}")
    print()

    # Group by case
    by_case = defaultdict(list)
    for r in all_records:
        by_case[r["case_id"]].append(r)

    print("=" * 100)
    print("  STAGE 2 VALIDATION REPORT")
    print("=" * 100)

    all_pass = True
    case_results = {}

    for case_id in sorted(CASE_META.keys()):
        recs = by_case.get(case_id, [])
        meta = CASE_META[case_id]
        family = meta["family"]

        print(f"\n{'─' * 80}")
        print(f"  {case_id} ({family})")
        print(f"{'─' * 80}")

        if not recs:
            print("  NO DATA")
            all_pass = False
            continue

        # --- Pass rates by condition ---
        by_cond = defaultdict(list)
        for r in recs:
            by_cond[r["condition"]].append(r)

        print(f"\n  Pass rates:")
        pass_rates = {}
        for cond in ["baseline_v2", "retry_leg_critique_strict_v2",
                      "retry_reasoning_only_critique_v1"]:
            cond_recs = by_cond.get(cond, [])
            if cond_recs:
                pr = sum(1 for r in cond_recs if r["passed"]) / len(cond_recs)
                n = len(cond_recs)
                pass_rates[cond] = pr
                short = {"baseline_v2": "base", "retry_leg_critique_strict_v2": "crit",
                         "retry_reasoning_only_critique_v1": "ro"}[cond]
                print(f"    {short:<8} {pr:>6.0%} ({n} trials)")

        # --- Per-model breakdown ---
        by_model_cond = defaultdict(lambda: defaultdict(list))
        for r in recs:
            by_model_cond[r["model"]][r["condition"]].append(r)

        print(f"\n  Per-model pass rates:")
        for model in sorted(by_model_cond.keys()):
            parts = f"    {model:<20}"
            for cond in ["baseline_v2", "retry_leg_critique_strict_v2",
                          "retry_reasoning_only_critique_v1"]:
                crs = by_model_cond[model].get(cond, [])
                if crs:
                    pr = sum(1 for r in crs if r["passed"]) / len(crs)
                    parts += f"  {pr:>5.0%}"
                else:
                    parts += f"  {'—':>5}"
            print(parts)

        # --- Gate 1: Floor/Ceiling ---
        base_pr = pass_rates.get("baseline_v2", -1)
        floor_ceil = "PASS"
        if base_pr >= 0.9:
            floor_ceil = "FAIL (ceiling)"
            all_pass = False
        elif base_pr == 0:
            floor_ceil = "FAIL (floor)"
            all_pass = False
        elif base_pr <= 0.1:
            floor_ceil = "WARN (near-floor)"
        print(f"\n  Gate: Floor/Ceiling:  {floor_ceil}  (baseline={base_pr:.0%})")

        # --- Gate 2: Observed Failure Pattern ---
        failures = [r for r in recs if not r["passed"]]
        n_failures = len(failures)
        if n_failures > 0:
            classifications = defaultdict(int)
            for r in failures:
                cat = classify_failure(r, meta)
                classifications[cat] += 1

            intended_match = classifications.get("attractor_chosen", 0)
            if family == "intervention_boundary":
                # For intervention_boundary, "true_fix_direction" IS the intended pattern
                intended_match = classifications.get("true_fix_direction", 0) + \
                                 classifications.get("attractor_chosen", 0)

            match_rate = intended_match / n_failures if n_failures > 0 else 0
            pattern_gate = "PASS" if match_rate >= 0.5 else "FAIL"

            print(f"  Gate: Failure Pattern: {pattern_gate}  "
                  f"({intended_match}/{n_failures} = {match_rate:.0%} match intended)")
            for cat, cnt in sorted(classifications.items()):
                print(f"    {cat}: {cnt} ({cnt/n_failures:.0%})")

            if pattern_gate == "FAIL":
                all_pass = False
        else:
            print(f"  Gate: Failure Pattern: N/A (no failures)")

        # --- Gate 3: Trap Activation ---
        if n_failures > 0:
            trap_rate = classifications.get("attractor_chosen", 0) / n_failures
            trap_gate = "PASS" if trap_rate >= 0.2 else "FAIL"
            if family == "intervention_boundary":
                # intervention_boundary: trap is incomplete fix, same file as root cause
                trap_rate = (classifications.get("true_fix_direction", 0) +
                             classifications.get("attractor_chosen", 0)) / n_failures
                trap_gate = "PASS" if trap_rate >= 0.2 else "FAIL"
            print(f"  Gate: Trap Activation: {trap_gate}  ({trap_rate:.0%} of failures)")
            if trap_gate == "FAIL":
                all_pass = False
        else:
            print(f"  Gate: Trap Activation: N/A (no failures)")

        # --- Gate 4: Intervention Probe ---
        delta_crit = pass_rates.get("retry_leg_critique_strict_v2", 0) - base_pr
        delta_ro = pass_rates.get("retry_reasoning_only_critique_v1", 0) - base_pr
        max_delta = max(abs(delta_crit), abs(delta_ro))
        sensitive = max_delta >= 0.10
        label = "intervention-SENSITIVE" if sensitive else "intervention-insensitive"
        print(f"  Gate: Intervention:   {label}  "
              f"(Δcrit={delta_crit:+.0%}, Δro={delta_ro:+.0%})")

        # --- Mechanism correctness ---
        mech_rates = {}
        for cond in ["baseline_v2", "retry_leg_critique_strict_v2",
                      "retry_reasoning_only_critique_v1"]:
            cond_recs = by_cond.get(cond, [])
            if cond_recs:
                mr = sum(1 for r in cond_recs if r["mechanism_correct"]) / len(cond_recs)
                mech_rates[cond] = mr

        leg_recs = [r for r in by_cond.get("baseline_v2", [])
                     if r["mechanism_correct"] and not r["passed"]]
        leg_rate = len(leg_recs) / len(by_cond.get("baseline_v2", [None])) if by_cond.get("baseline_v2") else 0
        print(f"  LEG rate (baseline):  {leg_rate:.0%}")
        print(f"  Mechanism correct:    base={mech_rates.get('baseline_v2', 0):.0%}  "
              f"crit={mech_rates.get('retry_leg_critique_strict_v2', 0):.0%}  "
              f"ro={mech_rates.get('retry_reasoning_only_critique_v1', 0):.0%}")

        # --- Fisher exact test ---
        base_n = len(by_cond.get("baseline_v2", []))
        base_pass = sum(1 for r in by_cond.get("baseline_v2", []) if r["passed"])
        for cond, label in [("retry_leg_critique_strict_v2", "crit"),
                             ("retry_reasoning_only_critique_v1", "ro")]:
            treat_recs = by_cond.get(cond, [])
            if treat_recs and base_n >= 10:
                treat_pass = sum(1 for r in treat_recs if r["passed"])
                treat_n = len(treat_recs)
                _, p = sp_stats.fisher_exact([
                    [base_pass, base_n - base_pass],
                    [treat_pass, treat_n - treat_pass],
                ])
                sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
                delta = treat_pass / treat_n - base_pass / base_n
                print(f"  Fisher ({label} vs base): Δ={delta:+.0%}  p={p:.4f} {sig}")

        case_results[case_id] = {
            "base_pr": base_pr,
            "delta_crit": delta_crit,
            "delta_ro": delta_ro,
            "sensitive": sensitive,
            "leg_rate": leg_rate,
            "family": family,
        }

    # --- Summary ---
    print(f"\n{'=' * 100}")
    print(f"  STAGE 2 SUMMARY")
    print(f"{'=' * 100}\n")

    header = f"{'Case':<28} {'Family':<24} {'Base%':>6} {'Δcrit':>7} {'Δro':>7} {'LEG%':>6} {'Sensitive':>12}"
    print(header)
    print("-" * len(header))
    for case_id, cr in sorted(case_results.items()):
        print(f"{case_id:<28} {cr['family']:<24} {cr['base_pr']:>5.0%} "
              f"{cr['delta_crit']:>+6.0%} {cr['delta_ro']:>+6.0%} "
              f"{cr['leg_rate']:>5.0%} {'YES' if cr['sensitive'] else 'no':>12}")

    # Promotion decision
    promoted = []
    for case_id, cr in case_results.items():
        if cr["base_pr"] > 0 and cr["base_pr"] < 0.9:
            promoted.append(case_id)
        elif cr["base_pr"] == 0:
            print(f"\n  DROP: {case_id} — floor (0% baseline)")
        elif cr["base_pr"] >= 0.9:
            print(f"\n  DROP: {case_id} — ceiling (≥90% baseline)")

    print(f"\n  PROMOTED: {len(promoted)}/{len(case_results)} cases")
    for c in promoted:
        print(f"    ✓ {c}")

    # Completion criteria check
    families_with_cases = defaultdict(list)
    for c in promoted:
        families_with_cases[case_results[c]["family"]].append(c)

    print(f"\n  Family coverage: {len(families_with_cases)} families with promoted cases")
    for fam, cases in sorted(families_with_cases.items()):
        print(f"    {fam}: {len(cases)} cases ({', '.join(cases)})")

    sensitive_count = sum(1 for c in promoted if case_results[c]["sensitive"])
    insensitive_count = len(promoted) - sensitive_count
    print(f"\n  Intervention-sensitive: {sensitive_count}")
    print(f"  Intervention-insensitive: {insensitive_count}")


if __name__ == "__main__":
    main()
