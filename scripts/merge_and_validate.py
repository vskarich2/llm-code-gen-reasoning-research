#!/usr/bin/env python
"""Merge per-run event files and validate tuple completeness.

Reads all events.jsonl files from ablation_runs/, merges into a single
sorted file, and validates that all expected (model, case_id, condition, trial)
tuples are present with no duplicates.

Usage:
    .venv/bin/python scripts/merge_and_validate.py \
        --ablation-dir logs/ablation_runs \
        --n-models 3 --n-cases 58 --n-conditions 2 --n-trials 8
"""

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_metrics import read_events_safe


def main():
    parser = argparse.ArgumentParser(description="Merge and validate ablation events")
    parser.add_argument("--ablation-dir", required=True)
    parser.add_argument("--n-models", type=int, required=True)
    parser.add_argument("--n-cases", type=int, required=True)
    parser.add_argument("--n-conditions", type=int, required=True)
    parser.add_argument("--n-trials", type=int, required=True)
    parser.add_argument("--output", default="logs/events_merged.jsonl")
    args = parser.parse_args()

    ablation_dir = Path(args.ablation_dir)
    expected_total = args.n_models * args.n_cases * args.n_conditions * args.n_trials

    # ============================================================
    # MERGE
    # ============================================================

    event_files = sorted(glob.glob(str(ablation_dir / "run_*" / "events.jsonl")))
    print(f"Discovered {len(event_files)} event files")

    all_events = []
    for ef in event_files:
        events = read_events_safe(Path(ef))
        all_events.extend(events)
    print(f"Total events read: {len(all_events)}")

    # Sort deterministically by (model, trial, case_id, condition)
    all_events.sort(key=lambda e: (
        e.get("model", ""),
        e.get("trial", 0),
        e.get("case_id", ""),
        e.get("condition", ""),
    ))

    # Write merged file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for event in all_events:
            f.write(json.dumps(event, default=str) + "\n")
    print(f"Merged file written: {output_path} ({len(all_events)} events)")

    # ============================================================
    # VALIDATE
    # ============================================================

    errors = []

    # Check required fields
    required_keys = {"model", "trial", "run_id", "case_id", "condition", "timestamp"}
    for i, e in enumerate(all_events):
        missing = required_keys - e.keys()
        if missing:
            errors.append(f"Event {i}: missing required keys {missing}")

    if errors:
        print(f"\nVALIDATION FAILED: {len(errors)} events with missing fields")
        for err in errors[:20]:
            print(f"  {err}")
        sys.exit(1)

    # Build tuple set
    tuples = [(e["model"], e["case_id"], e["condition"], e["trial"]) for e in all_events]
    unique_tuples = set(tuples)
    tuple_counts = Counter(tuples)

    # Check total unique tuples
    if len(unique_tuples) != expected_total:
        print(f"\nVALIDATION FAILED: expected {expected_total} unique tuples, "
              f"found {len(unique_tuples)}")
        errors.append("Total unique tuple count mismatch")

    # Check duplicates
    duplicates = {t: c for t, c in tuple_counts.items() if c > 1}
    if duplicates:
        print(f"\nVALIDATION FAILED: {len(duplicates)} duplicate tuples")
        for t, c in sorted(duplicates.items())[:20]:
            print(f"  {t}: {c} occurrences")
        errors.append("Duplicate tuples found")

    # Check per-model counts
    models = sorted(set(e["model"] for e in all_events))
    per_model_expected = args.n_cases * args.n_conditions * args.n_trials
    for model in models:
        count = sum(1 for e in all_events if e["model"] == model)
        if count != per_model_expected:
            msg = f"Model {model}: expected {per_model_expected}, found {count}"
            print(f"  {msg}")
            errors.append(msg)

    if len(models) != args.n_models:
        msg = f"Expected {args.n_models} models, found {len(models)}: {models}"
        print(f"  {msg}")
        errors.append(msg)

    # Check per-condition counts
    conditions = sorted(set(e["condition"] for e in all_events))
    per_cond_expected = args.n_models * args.n_cases * args.n_trials
    for cond in conditions:
        count = sum(1 for e in all_events if e["condition"] == cond)
        if count != per_cond_expected:
            msg = f"Condition {cond}: expected {per_cond_expected}, found {count}"
            print(f"  {msg}")
            errors.append(msg)

    # Check per (model, case_id, condition) trial count
    from collections import defaultdict
    mcc_trials = defaultdict(set)
    for e in all_events:
        key = (e["model"], e["case_id"], e["condition"])
        mcc_trials[key].add(e["trial"])

    for key, trials in sorted(mcc_trials.items()):
        if len(trials) != args.n_trials:
            msg = f"{key}: expected {args.n_trials} trials, found {len(trials)} ({sorted(trials)})"
            errors.append(msg)

    trial_violations = [k for k, v in mcc_trials.items() if len(v) != args.n_trials]
    if trial_violations:
        print(f"\nVALIDATION FAILED: {len(trial_violations)} (model, case, condition) groups "
              f"with wrong trial count")
        for v in trial_violations[:20]:
            print(f"  {v}: {sorted(mcc_trials[v])}")

    # Check for missing tuples
    case_ids = sorted(set(e["case_id"] for e in all_events))
    trials = sorted(set(e["trial"] for e in all_events))
    expected_tuples = set()
    for m in models:
        for c in case_ids:
            for cond in conditions:
                for t in trials:
                    expected_tuples.add((m, c, cond, t))

    missing = expected_tuples - unique_tuples
    if missing:
        print(f"\nVALIDATION FAILED: {len(missing)} missing tuples")
        for m in sorted(missing)[:20]:
            print(f"  {m}")
        errors.append(f"{len(missing)} missing tuples")

    # ============================================================
    # RESULT
    # ============================================================

    if errors:
        print(f"\nVALIDATION FAILED: {len(errors)} error(s)")
        sys.exit(1)

    print(f"\nVALIDATION PASSED: {len(all_events)} events, "
          f"{len(models)} models, {len(case_ids)} cases, "
          f"{len(conditions)} conditions, {len(trials)} trials")
    sys.exit(0)


if __name__ == "__main__":
    main()
