#!/usr/bin/env python
"""Post-hoc shadow analysis: compare baseline vs retry conditions.

Usage:
    python scripts/shadow_analysis.py logs/gpt-4o-mini_TIMESTAMP.jsonl

Reads a SINGLE metadata log file that contains multiple conditions
(baseline + retry variants) for the same cases. Produces comparison tables.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


def load_summaries(log_path):
    """Load summary records from a metadata JSONL file."""
    summaries = {}  # (case_id, condition) -> summary
    with open(log_path) as f:
        for line in f:
            record = json.loads(line)
            if record.get("iteration") == "summary":
                key = (record["case_id"], record["condition"])
                summaries[key] = record
    return summaries


def load_baselines(log_path):
    """Load baseline (non-retry) records."""
    baselines = {}
    with open(log_path) as f:
        for line in f:
            record = json.loads(line)
            if record.get("condition") == "baseline" and record.get("iteration") != "summary":
                baselines[record["case_id"]] = record
    return baselines


def analyze(log_path):
    summaries = load_summaries(log_path)
    baselines = load_baselines(log_path)

    # Group by case
    cases = set()
    conditions = set()
    for (cid, cond) in summaries:
        cases.add(cid)
        conditions.add(cond)
    for cid in baselines:
        cases.add(cid)
    conditions = sorted(conditions)
    cases = sorted(cases)

    # Validation
    for cid in cases:
        if cid not in baselines:
            print(f"WARNING: no baseline for {cid}")

    # Per-case comparison
    print(f"\n{'Case':<30}", end="")
    print(f"{'BL':>6}", end="")
    for cond in conditions:
        label = cond.replace("retry_", "r_")[:8]
        print(f"{label:>10}", end="")
    print()
    print("-" * (30 + 6 + 10 * len(conditions)))

    recovery_counts = defaultdict(lambda: {"recovered": 0, "total_fail": 0})
    failure_type_recovery = defaultdict(lambda: defaultdict(lambda: {"pass": 0, "total": 0}))

    for cid in cases:
        bl = baselines.get(cid, {})
        bl_pass = bl.get("evaluation", {}).get("pass", False)
        bl_score = bl.get("evaluation", {}).get("score", 0)

        print(f"{cid:<30}", end="")
        print(f"{'P' if bl_pass else 'F':>3}{bl_score:>3.1f}", end="")

        for cond in conditions:
            s = summaries.get((cid, cond))
            if not s:
                print(f"{'---':>10}", end="")
                continue
            sp = s.get("converged", False)
            ss = s.get("metrics", {}).get("score_trajectory", [0])[-1] if s.get("metrics") else 0
            iters = s.get("total_iterations_executed", 0)
            mark = "P" if sp else "F"
            print(f"{mark:>3}{ss:>3.1f}({iters})", end="")

            # Track recovery
            if not bl_pass:
                recovery_counts[cond]["total_fail"] += 1
                if sp:
                    recovery_counts[cond]["recovered"] += 1

            # Track by failure type
            for e in s.get("trajectory", []):
                ft = e.get("failure_type")
                if ft:
                    failure_type_recovery[ft][cond]["total"] += 1
                    if s.get("converged"):
                        failure_type_recovery[ft][cond]["pass"] += 1

        print()

    # Aggregate metrics
    print(f"\n{'='*60}")
    print("AGGREGATE METRICS")
    print(f"{'='*60}\n")

    for cond in conditions:
        rc = recovery_counts[cond]
        rate = rc["recovered"] / rc["total_fail"] if rc["total_fail"] else 0
        print(f"{cond}: recovered {rc['recovered']}/{rc['total_fail']} baseline failures ({rate:.0%})")

    # Recovery by failure type
    all_types = sorted(failure_type_recovery.keys())
    if all_types:
        print(f"\n{'Failure Type':<25}", end="")
        for cond in conditions:
            label = cond.replace("retry_", "")[:10]
            print(f"{label:>12}", end="")
        print()
        print("-" * (25 + 12 * len(conditions)))
        for ft in all_types:
            print(f"{ft:<25}", end="")
            for cond in conditions:
                d = failure_type_recovery[ft][cond]
                if d["total"] > 0:
                    rate = d["pass"] / d["total"]
                    print(f"{rate:>8.0%}({d['total']})", end="")
                else:
                    print(f"{'---':>12}", end="")
            print()

    # Delta: adaptive vs no_contract
    if "retry_adaptive" in conditions and "retry_no_contract" in conditions:
        print(f"\nDELTA (adaptive - no_contract) by failure type:")
        for ft in all_types:
            adapt = failure_type_recovery[ft].get("retry_adaptive", {"pass": 0, "total": 0})
            nocon = failure_type_recovery[ft].get("retry_no_contract", {"pass": 0, "total": 0})
            p_adapt = adapt["pass"] / adapt["total"] if adapt["total"] else 0
            p_nocon = nocon["pass"] / nocon["total"] if nocon["total"] else 0
            delta = p_adapt - p_nocon
            if adapt["total"] > 0 or nocon["total"] > 0:
                print(f"  {ft:<25} P(adapt)={p_adapt:.2f}  P(no_con)={p_nocon:.2f}  delta={delta:+.2f}")


def main():
    parser = argparse.ArgumentParser(description="Shadow analysis: compare baseline vs retry")
    parser.add_argument("log_file", help="Path to metadata .jsonl file")
    args = parser.parse_args()

    if not Path(args.log_file).exists():
        print(f"File not found: {args.log_file}")
        sys.exit(1)

    analyze(args.log_file)


if __name__ == "__main__":
    main()
