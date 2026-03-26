#!/usr/bin/env python
"""Cost protection gate: validate smoke run results before full ablation.

Checks:
  1. Evaluator sanity: reference fix for canary case passes exec_evaluate ($0)
  2. Event-level: total > 0, ran_rate >= 50%, pass_count > 0
  3. Canary case ran == True

Exit 0 = PASS, exit 1 = FAIL (abort ablation).

Usage:
    .venv/bin/python scripts/validate_smoke.py --run-dir logs/ablation_runs/gate_xxx --cases cases_v2.json --canary alias_config_a --verbose
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_metrics import read_events_safe


def validate_evaluator_sanity(canary_id: str, cases_file: str) -> bool:
    """Run reference fix for canary through exec_evaluate. $0 cost."""
    from runner import load_cases
    from exec_eval import exec_evaluate
    from validate_cases_v2 import load_reference_code

    cases = load_cases(cases_file=cases_file)
    canary = next((c for c in cases if c["id"] == canary_id), None)
    if canary is None:
        print(f"  EVALUATOR SANITY: canary case '{canary_id}' not found")
        return False

    ref_code = load_reference_code(canary)
    if ref_code is None:
        print(f"  EVALUATOR SANITY: no reference fix for '{canary_id}'")
        return False

    result = exec_evaluate(canary, ref_code)
    if result["pass"]:
        print(f"  EVALUATOR SANITY: PASS (canary '{canary_id}' reference fix passes)")
        return True
    else:
        print(f"  EVALUATOR SANITY: FAIL — reference fix does not pass for '{canary_id}'")
        print(f"    ran={result['execution'].get('ran')}")
        print(f"    reasons={result.get('reasons', [])}")
        return False


def validate_events(run_dir: Path, canary_id: str, verbose: bool) -> bool:
    """Validate events from a gate run."""
    events_path = run_dir / "events.jsonl"
    events = read_events_safe(events_path)
    total = len(events)

    if total == 0:
        print("  EVENTS: FAIL — zero events produced")
        return False

    passes = sum(1 for e in events if e.get("pass"))
    # Estimate ran from score > 0 or pass == True
    ran = sum(1 for e in events if e.get("pass") or e.get("score", 0) > 0)
    ran_rate = ran / total if total > 0 else 0

    # Check canary
    canary_events = [e for e in events if e.get("case_id") == canary_id]
    canary_ran = any(e.get("pass") or e.get("score", 0) > 0 for e in canary_events)

    print(f"  EVENTS: total={total}, passes={passes}, ran~={ran} ({ran_rate:.0%})")

    if verbose:
        print("  Per-event breakdown:")
        for e in events[:10]:
            print(f"    {e.get('case_id', '?')}/{e.get('condition', '?')}: "
                  f"pass={e.get('pass')}, score={e.get('score', 0)}")

    ok = True
    if passes == 0:
        print("  EVENTS: FAIL — zero passes")
        ok = False
    if ran_rate < 0.5:
        print(f"  EVENTS: FAIL — ran_rate {ran_rate:.0%} < 50%")
        ok = False
    if not canary_ran and canary_events:
        print(f"  EVENTS: FAIL — canary '{canary_id}' did not run")
        ok = False

    if ok:
        print("  EVENTS: PASS")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Validate smoke run for cost protection")
    parser.add_argument("--run-dir", required=True, help="Gate run directory")
    parser.add_argument("--cases", default="cases_v2.json", help="Cases file")
    parser.add_argument("--canary", default="alias_config_a", help="Canary case ID")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    print("=" * 60)
    print("  COST PROTECTION GATE")
    print("=" * 60)

    # Step 1: Evaluator sanity ($0)
    eval_ok = validate_evaluator_sanity(args.canary, args.cases)

    # Step 2: Event validation
    events_ok = validate_events(run_dir, args.canary, args.verbose)

    print()
    if eval_ok and events_ok:
        print("  GATE RESULT: PASS")
        print("=" * 60)
        sys.exit(0)
    else:
        print("  GATE RESULT: FAIL — aborting ablation")
        if not eval_ok:
            print("  Diagnosis: Evaluator is broken. exec_evaluate does not pass reference fix.")
        if not events_ok:
            print("  Diagnosis: Pipeline produced degenerate results. Check wiring.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
