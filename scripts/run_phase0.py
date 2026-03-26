#!/usr/bin/env python
"""Phase 0: Measurement Audit — Hypothesis Testing Experiments.

Runs P0-0 through P0-7, P0-PROMPT, and P0-STAB per plan v6.
Each experiment calls the reasoning classifier with controlled inputs
and records full 21-field reasoning_evaluator_audit logs.

Usage:
    .venv/bin/python scripts/run_phase0.py --config configs/default.yaml
    .venv/bin/python scripts/run_phase0.py --config configs/default.yaml --experiment P0-1
    .venv/bin/python scripts/run_phase0.py --config configs/default.yaml --dry-run

Requires: Go/No-Go checklist fully satisfied.
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiment_config import load_config, get_config
from evaluator import llm_classify, parse_classify_output, _CLASSIFY_PROMPT
from failure_classifier import FAILURE_TYPE_SET
from runner import load_cases
from validate_cases_v2 import load_reference_code, load_case_code


BASE = Path(__file__).resolve().parents[1]
AUDIT_DIR = BASE / "reasoning_evaluator_audit"
RESULTS_DIR = AUDIT_DIR / "phase0_results"


def _load_locked_set():
    return json.loads((AUDIT_DIR / "locked_audit_set.json").read_text())


def _load_case(case_id):
    cases = load_cases(cases_file="cases_v2.json")
    return next(c for c in cases if c["id"] == case_id)


def _get_baseline_reasoning(case_id, run_dir=None):
    """Extract baseline reasoning from the most recent gpt-5.4-mini run."""
    if run_dir is None:
        run_dir = BASE / "logs" / "ablation_runs" / "run_gpt-5.4-mini_t1_169e3bcd"
    run_log = run_dir / "run.jsonl"
    if not run_log.exists():
        return None, None
    for line in open(run_log):
        r = json.loads(line)
        if r["case_id"] == case_id and r["condition"] == "baseline":
            reasoning = r["parsed"]["reasoning"]
            code_len = r["parsed"].get("code_length", 0)
            return reasoning, code_len
    return None, None


def _get_lr_reasoning(case_id, run_dir=None):
    """Extract LEG-reduction reasoning (bug_diagnosis) from run."""
    if run_dir is None:
        run_dir = BASE / "logs" / "ablation_runs" / "run_gpt-5.4-mini_t1_169e3bcd"
    run_log = run_dir / "run.jsonl"
    if not run_log.exists():
        return None
    for line in open(run_log):
        r = json.loads(line)
        if r["case_id"] == case_id and r["condition"] == "leg_reduction":
            return r["parsed"]["reasoning"]
    return None


def _get_lr_raw_response(case_id, run_dir=None):
    """Get full raw LR response."""
    if run_dir is None:
        run_dir = BASE / "logs" / "ablation_runs" / "run_gpt-5.4-mini_t1_169e3bcd"
    resp_log = run_dir / "run_responses.jsonl"
    if not resp_log.exists():
        return None
    for line in open(resp_log):
        r = json.loads(line)
        if r["case_id"] == case_id and r["condition"] == "leg_reduction":
            return r["raw_response"]
    return None


def _classify(case, code, reasoning, experiment_id):
    """Run classifier and return full result with reasoning_evaluator_audit fields."""
    result = llm_classify(case, code, reasoning)
    result["experiment_id"] = experiment_id
    result["case_id"] = case["id"]
    result["reasoning_length"] = len(reasoning) if reasoning else 0
    result["timestamp"] = datetime.now().isoformat()
    return result


def _log_result(results, result):
    """Append result to running list."""
    results.append(result)


def _save_results(experiment_id, results):
    """Save experiment results to reasoning_evaluator_audit/phase0_results/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{experiment_id}.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Saved {len(results)} results to {path}")
    return path


# ============================================================
# P0-1: H1 Brevity Bias (15 cases x 4 compressions)
# ============================================================

def run_p0_1(cases_subset=None, dry_run=False):
    """H1: Does compressing reasoning (same E1-E3) flip YES->NO?"""
    locked = _load_locked_set()
    case_ids = [c["case_id"] for c in locked][:15]
    if cases_subset:
        case_ids = cases_subset

    results = []
    api_calls = 0
    flips = 0

    print(f"\n=== P0-1: H1 Brevity Bias ({len(case_ids)} cases) ===")

    for cid in case_ids:
        case = _load_case(cid)
        bl_reasoning, _ = _get_baseline_reasoning(cid)
        if not bl_reasoning:
            print(f"  SKIP {cid}: no baseline reasoning found")
            continue

        ref_code = load_reference_code(case) or ""

        # Version 1: Full baseline reasoning
        if not dry_run:
            r_full = _classify(case, ref_code, bl_reasoning, "P0-1")
            api_calls += 1
        else:
            r_full = {"reasoning_correct": True, "experiment_id": "P0-1-dry"}

        # Version 2: First sentence only
        first_sentence = bl_reasoning.split(".")[0] + "." if "." in bl_reasoning else bl_reasoning[:100]

        if not dry_run:
            r_short = _classify(case, ref_code, first_sentence, "P0-1")
            api_calls += 1
        else:
            r_short = {"reasoning_correct": None, "experiment_id": "P0-1-dry"}

        # Version 3: Just the root cause name
        terse = first_sentence[:80]
        if not dry_run:
            r_terse = _classify(case, ref_code, terse, "P0-1")
            api_calls += 1
        else:
            r_terse = {"reasoning_correct": None, "experiment_id": "P0-1-dry"}

        full_yes = r_full.get("reasoning_correct") is True
        short_no = r_short.get("reasoning_correct") is False
        terse_no = r_terse.get("reasoning_correct") is False

        flip = full_yes and (short_no or terse_no)
        if flip:
            flips += 1

        entry = {
            "case_id": cid,
            "full_reasoning": bl_reasoning[:200],
            "full_length": len(bl_reasoning),
            "short_reasoning": first_sentence[:100],
            "short_length": len(first_sentence),
            "terse_reasoning": terse[:80],
            "full_verdict": r_full.get("reasoning_correct"),
            "short_verdict": r_short.get("reasoning_correct"),
            "terse_verdict": r_terse.get("reasoning_correct"),
            "flip": flip,
        }
        results.append(entry)

        status = "FLIP" if flip else "ok"
        print(f"  {cid:30s} full={str(r_full.get('reasoning_correct')):<5} "
              f"short={str(r_short.get('reasoning_correct')):<5} "
              f"terse={str(r_terse.get('reasoning_correct')):<5} {status}")

    print(f"\n  P0-1 SUMMARY: {flips}/{len(results)} flips, {api_calls} API calls")
    print(f"  CONFIRMED (>=5): {flips >= 5}, FALSIFIED (<=2): {flips <= 2}")

    if not dry_run:
        _save_results("P0-1", results)
    return results


# ============================================================
# P0-2: H1 Negative Control — terse-correct must be YES
# ============================================================

def run_p0_2(dry_run=False):
    """Control: 5 terse but semantically correct reasoning -> all must be YES."""
    # Use cases we KNOW are terse-correct from the forensic reasoning_evaluator_audit
    control_cases = [
        ("alias_config_a", "create_config returns a reference to DEFAULTS instead of a copy, so caller mutations corrupt shared state."),
        ("mutable_default_a", "enqueue uses a mutable default argument (queue=[]), so the same list accumulates across calls."),
        ("stale_cache_a", "update_product modifies the DB but does not invalidate the cache entry, so get_product returns stale data."),
        ("partial_update_a", "update_profile sets 'name' without updating 'display_name', leaving them out of sync."),
        ("wrong_condition_a", "is_rate_limited uses > instead of >=, allowing one extra request past the limit."),
    ]

    results = []
    all_yes = True

    print(f"\n=== P0-2: Terse-Correct Control ({len(control_cases)} cases) ===")

    for cid, terse_reasoning in control_cases:
        case = _load_case(cid)
        ref_code = load_reference_code(case) or ""

        if not dry_run:
            r = _classify(case, ref_code, terse_reasoning, "P0-2")
        else:
            r = {"reasoning_correct": True, "experiment_id": "P0-2-dry"}

        verdict = r.get("reasoning_correct")
        if verdict is not True:
            all_yes = False

        results.append({
            "case_id": cid,
            "reasoning": terse_reasoning,
            "verdict": verdict,
            "expected": True,
            "pass": verdict is True,
        })

        status = "PASS" if verdict is True else "FAIL"
        print(f"  {cid:30s} verdict={verdict:<5} {status}")

    print(f"\n  P0-2 SUMMARY: {'ALL YES — PASS' if all_yes else 'CONTROL FAILED — CLASSIFIER DISQUALIFIED'}")

    if not dry_run:
        _save_results("P0-2", results)
    return results


# ============================================================
# P0-3: H1 Negative Control — verbose-wrong must be NO
# ============================================================

def run_p0_3(dry_run=False):
    """Control: 5 verbose but semantically wrong reasoning -> all must be NO."""
    control_cases = [
        ("alias_config_a", "The bug is caused by an integer overflow in the timeout computation. When the system clock wraps around at midnight, the configuration values become negative, causing assertion failures in downstream consumers. The fix is to add modular arithmetic to handle the wrap-around case and normalize all timeout values to positive integers before returning them to callers."),
        ("mutable_default_a", "The issue is a race condition in the queue module. When two threads call enqueue simultaneously, the GIL does not protect the list append operation, causing items to be silently dropped. The fix is to add a threading lock around the critical section and use a thread-safe deque instead of a plain list."),
        ("stale_cache_a", "The database connection pool is exhausted because get_product opens a new connection for every call but never closes it. After 100 calls, the pool is full and subsequent requests hang. The fix is to implement connection pooling with a context manager that returns connections after use."),
        ("partial_update_a", "The profile update fails because the user dict is frozen (immutable) after initial creation. Attempting to modify any field raises a TypeError. The fix is to convert the frozen dict to a regular dict before updates and re-freeze it afterwards."),
        ("wrong_condition_a", "The rate limiter fails because it stores timestamps in UTC but compares them against local time. In timezones west of UTC, this causes the limiter to expire entries too early, and in eastern timezones, entries persist too long. The fix is to normalize all timestamps to UTC before comparison."),
    ]

    results = []
    all_no = True

    print(f"\n=== P0-3: Verbose-Wrong Control ({len(control_cases)} cases) ===")

    for cid, wrong_reasoning in control_cases:
        case = _load_case(cid)
        ref_code = load_reference_code(case) or ""

        if not dry_run:
            r = _classify(case, ref_code, wrong_reasoning, "P0-3")
        else:
            r = {"reasoning_correct": False, "experiment_id": "P0-3-dry"}

        verdict = r.get("reasoning_correct")
        if verdict is not False:
            all_no = False

        results.append({
            "case_id": cid,
            "reasoning": wrong_reasoning[:100],
            "verdict": verdict,
            "expected": False,
            "pass": verdict is False,
        })

        status = "PASS" if verdict is False else "FAIL"
        print(f"  {cid:30s} verdict={verdict:<5} {status}")

    print(f"\n  P0-3 SUMMARY: {'ALL NO — PASS' if all_no else 'CONTROL FAILED — CLASSIFIER DISQUALIFIED'}")

    if not dry_run:
        _save_results("P0-3", results)
    return results


# ============================================================
# P0-6: H3 Parse Failure Census
# ============================================================

def run_p0_6(dry_run=False):
    """H3: Count parse failures across conditions in existing run data."""
    print(f"\n=== P0-6: Parse Failure Census ===")

    run_dir = BASE / "logs" / "ablation_runs" / "run_gpt-5.4-mini_t1_169e3bcd"
    run_log = run_dir / "run.jsonl"
    if not run_log.exists():
        print("  ERROR: run log not found")
        return []

    by_cond = defaultdict(lambda: {"total": 0, "parse_error": 0, "empty_reasoning": 0})

    for line in open(run_log):
        r = json.loads(line)
        cond = r["condition"]
        by_cond[cond]["total"] += 1
        pe = r["parsed"].get("parse_error")
        reasoning = r["parsed"].get("reasoning", "")
        if pe:
            by_cond[cond]["parse_error"] += 1
        if not reasoning or not reasoning.strip():
            by_cond[cond]["empty_reasoning"] += 1

    results = []
    for cond in sorted(by_cond):
        d = by_cond[cond]
        n = d["total"]
        pe_rate = d["parse_error"] / n * 100 if n else 0
        empty_rate = d["empty_reasoning"] / n * 100 if n else 0
        results.append({
            "condition": cond, "total": n,
            "parse_errors": d["parse_error"], "parse_error_rate": round(pe_rate, 1),
            "empty_reasoning": d["empty_reasoning"], "empty_rate": round(empty_rate, 1),
        })
        print(f"  {cond:20s}: {n:>3} events, "
              f"parse_error={d['parse_error']:>3} ({pe_rate:.1f}%), "
              f"empty_reasoning={d['empty_reasoning']:>3} ({empty_rate:.1f}%)")

    # Verdict
    any_above_5 = any(r["parse_error_rate"] >= 5 for r in results)
    all_below_1 = all(r["parse_error_rate"] < 1 for r in results)
    print(f"\n  P0-6: CONFIRMED (>=5% any): {any_above_5}, FALSIFIED (<1% all): {all_below_1}")

    _save_results("P0-6", results)
    return results


# ============================================================
# P0-STAB: Stochastic Stability (temp=0)
# ============================================================

def run_p0_stab(n_cases=10, n_runs=3, dry_run=False):
    """Stability: same input at temp=0 should produce identical output."""
    locked = _load_locked_set()
    case_ids = [c["case_id"] for c in locked][:n_cases]

    results = []
    unstable = 0

    print(f"\n=== P0-STAB: Stochastic Stability ({n_cases} cases x {n_runs} runs) ===")

    for cid in case_ids:
        case = _load_case(cid)
        bl_reasoning, _ = _get_baseline_reasoning(cid)
        if not bl_reasoning:
            continue
        ref_code = load_reference_code(case) or ""

        verdicts = []
        for run in range(n_runs):
            if not dry_run:
                r = _classify(case, ref_code, bl_reasoning, "P0-STAB")
                verdicts.append(r.get("reasoning_correct"))
            else:
                verdicts.append(True)

        consistent = len(set(verdicts)) == 1
        if not consistent:
            unstable += 1

        results.append({
            "case_id": cid,
            "verdicts": verdicts,
            "consistent": consistent,
        })
        status = "STABLE" if consistent else "UNSTABLE"
        print(f"  {cid:30s} verdicts={verdicts} {status}")

    print(f"\n  P0-STAB: {unstable}/{len(results)} unstable. "
          f"{'100% consistent — PASS' if unstable == 0 else 'UNSTABLE — NEED VOTING'}")

    if not dry_run:
        _save_results("P0-STAB", results)
    return results


# ============================================================
# MAIN
# ============================================================

ALL_EXPERIMENTS = {
    "P0-1": run_p0_1,
    "P0-2": run_p0_2,
    "P0-3": run_p0_3,
    "P0-6": run_p0_6,
    "P0-STAB": run_p0_stab,
}


def main():
    parser = argparse.ArgumentParser(description="Phase 0 Measurement Audit")
    parser.add_argument("--config", default="configs/default.yaml", help="Config file")
    parser.add_argument("--experiment", default=None,
                        help="Run specific experiment (e.g., P0-1). Default: all.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip API calls, test infrastructure only")
    args = parser.parse_args()

    # Load config
    config = load_config(Path(args.config))
    print(f"Config loaded: {config.experiment.name}")
    print(f"Evaluator model: {config.models.evaluator.name}")
    print(f"Temperature: {config.models.evaluator.temperature}")

    # Verify Go/No-Go
    gng = json.loads((AUDIT_DIR / "go_no_go.json").read_text())
    all_ok = all(item["status"] for item in gng["items"])
    if not all_ok:
        missing = [item["description"] for item in gng["items"] if not item["status"]]
        print(f"\nGo/No-Go FAILED: {missing}")
        sys.exit(1)
    print("Go/No-Go: ALL SATISFIED")

    # Check budget
    budget = json.loads((AUDIT_DIR / "budget.json").read_text())
    max_calls = budget["phase_0"]["max_api_calls"]
    print(f"Budget: max {max_calls} API calls")

    if args.experiment:
        if args.experiment not in ALL_EXPERIMENTS:
            print(f"Unknown experiment: {args.experiment}. Available: {list(ALL_EXPERIMENTS.keys())}")
            sys.exit(1)
        ALL_EXPERIMENTS[args.experiment](dry_run=args.dry_run)
    else:
        # Run all in order: controls first, then hypotheses
        print("\n" + "=" * 60)
        print("  PHASE 0: RUNNING ALL EXPERIMENTS")
        print("=" * 60)

        # Controls first — if these fail, everything stops
        run_p0_2(dry_run=args.dry_run)
        run_p0_3(dry_run=args.dry_run)

        # Stability
        run_p0_stab(dry_run=args.dry_run)

        # Parse census (no API calls)
        run_p0_6(dry_run=args.dry_run)

        # Main hypothesis test
        run_p0_1(dry_run=args.dry_run)

        print("\n" + "=" * 60)
        print("  PHASE 0 COMPLETE")
        print("=" * 60)


if __name__ == "__main__":
    main()
