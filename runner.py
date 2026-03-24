# ============================================================
# T3 Code Generation — Multi-Condition Experiment Runner
#
# Run:  python runner.py
#       python runner.py --model gpt-4o-mini
#       python runner.py --case-id l3_state_pipeline
#       python runner.py --conditions baseline,diagnostic
#       python runner.py --parallel 8
# ============================================================

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from execution import (
    build_prompt, run_single, run_repair_loop, run_contract_gated,
    run_leg_reduction,
    init_run_log, close_run_log, get_current_log_path, get_log_write_stats,
)

BASE_DIR = Path(__file__).parent

# Model used for LEG evaluation (independent of generation model)
LEG_EVAL_MODEL = "gpt-5-mini"

ALL_CONDITIONS = [
    "baseline", "diagnostic", "guardrail",
    "guardrail_strict", "counterfactual", "reason_then_act",
    "self_check", "counterfactual_check", "test_driven",
    "repair_loop",
    # SCM experiment conditions
    "scm_descriptive", "scm_constrained", "scm_constrained_evidence",
    "scm_constrained_evidence_minimal", "evidence_only", "length_matched_control",
    # Reasoning interface conditions
    "structured_reasoning", "free_form_reasoning", "branching_reasoning",
    # Contract-Gated Execution
    "contract_gated",
    # Retry harness (trajectory probe)
    "retry_no_contract", "retry_with_contract", "retry_adaptive",
    "retry_alignment",
    # LEG-reduction (intra-call self-correction)
    "leg_reduction",
]
VALID_CONDITIONS = set(ALL_CONDITIONS)

COND_LABELS = {
    "baseline": "BL", "diagnostic": "DX", "guardrail": "GR",
    "guardrail_strict": "GS", "counterfactual": "CF", "reason_then_act": "RA",
    "self_check": "SC", "counterfactual_check": "CC", "test_driven": "TD",
    "repair_loop": "RL",
    "scm_descriptive": "SD", "scm_constrained": "SK", "scm_constrained_evidence": "SE",
    "scm_constrained_evidence_minimal": "SM", "evidence_only": "EO", "length_matched_control": "LC",
    "structured_reasoning": "SR", "free_form_reasoning": "FF", "branching_reasoning": "BR",
    "contract_gated": "CG",
    "retry_no_contract": "RN", "retry_with_contract": "RC", "retry_adaptive": "AD",
    "retry_alignment": "AL",
    "leg_reduction": "LR",
}

# INVARIANT: condition labels must be unique — duplicate labels corrupt results
assert len(set(COND_LABELS.values())) == len(COND_LABELS), (
    f"FATAL: Duplicate condition labels detected. "
    f"Labels: {[v for v in COND_LABELS.values() if list(COND_LABELS.values()).count(v) > 1]}"
)

COND_DESCRIPTIONS = {
    "baseline": "Baseline (terse)",
    "diagnostic": "Diagnostic operator",
    "guardrail": "Guardrail (soft)",
    "guardrail_strict": "Guardrail (strict/hard)",
    "counterfactual": "Counterfactual simulation",
    "reason_then_act": "Reason-then-act",
    "self_check": "Self-check (post-gen verify)",
    "counterfactual_check": "Counterfactual failure check",
    "test_driven": "Test-driven invariants",
    "repair_loop": "Repair loop (2 attempts)",
    "scm_descriptive": "SCM descriptive",
    "scm_constrained": "SCM constrained",
    "scm_constrained_evidence": "SCM evidence (full)",
    "scm_constrained_evidence_minimal": "SCM evidence (minimal)",
    "evidence_only": "Evidence only (no graph)",
    "length_matched_control": "Length-matched control",
    "structured_reasoning": "Structured reasoning",
    "free_form_reasoning": "Free-form reasoning",
    "branching_reasoning": "Branching reasoning (ToT-lite)",
    "contract_gated": "Contract-Gated Execution",
    "retry_no_contract": "Retry harness (no contract)",
    "retry_with_contract": "Retry harness (with contract)",
    "retry_adaptive": "Retry harness (adaptive hints)",
    "retry_alignment": "Retry harness (plan-code alignment)",
    "leg_reduction": "LEG-reduction (intra-call self-correction)",
}

REPAIR_LOOP_MAX_ATTEMPTS = 2

# Canonical imports are from execution.py. No aliases.


# ============================================================
# LOAD CASES
# ============================================================

def load_cases(case_id: str | None = None, cases_file: str = "cases.json") -> list[dict]:
    cases_path = BASE_DIR / cases_file
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    for case in cases:
        code_files = {}
        for rel_path in case["code_files"]:
            full_path = BASE_DIR / rel_path
            code_files[rel_path] = full_path.read_text(encoding="utf-8").strip()
        case["code_files_contents"] = code_files
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise ValueError(f"No case with id={case_id!r}")
    return cases


def preflight_verify_tests(cases: list[dict]) -> None:
    """Verify every case has a resolvable test function BEFORE running.

    If any case cannot be evaluated, the experiment MUST NOT proceed.
    Partial execution of unsupported cases is forbidden.
    """
    from exec_eval import _CASE_TESTS, _load_v2_test

    missing = []
    for case in cases:
        cid = case["id"]
        test_fn = _CASE_TESTS.get(cid)
        if test_fn is None:
            test_fn = _load_v2_test(case)
        if test_fn is None:
            missing.append(cid)

    if missing:
        raise RuntimeError(
            f"PREFLIGHT FAILURE: {len(missing)} case(s) have NO test function. "
            f"These cases CANNOT be evaluated and would silently score 0.0.\n"
            f"Missing: {missing}\n"
            f"Fix: add test functions or remove cases from the experiment."
        )


# ============================================================
# RUN ALL — parallel or serial
# ============================================================

def _run_one(case: dict, model: str, condition: str) -> tuple[str, str, dict]:
    import threading
    tid = threading.current_thread().name
    cid = case["id"]
    _log = __import__("logging").getLogger("t3.runner")
    _log.info("TASK_START thread=%s case=%s cond=%s", tid, cid, condition)
    t0 = __import__("time").monotonic()
    try:
        result = _run_one_inner(case, model, condition)
        elapsed = __import__("time").monotonic() - t0
        _log.info("TASK_END thread=%s case=%s cond=%s elapsed=%.1fs pass=%s",
                   tid, cid, condition, elapsed, result[2].get("pass"))
        return result
    except Exception as e:
        elapsed = __import__("time").monotonic() - t0
        _log.error("TASK_FAILED thread=%s case=%s cond=%s elapsed=%.1fs error=%s",
                    tid, cid, condition, elapsed, e)
        raise


def _run_one_inner(case: dict, model: str, condition: str) -> tuple[str, str, dict]:
    if condition == "repair_loop":
        return run_repair_loop(case, model)
    if condition == "contract_gated":
        return run_contract_gated(case, model)
    if condition == "retry_no_contract":
        from retry_harness import run_retry_harness
        return run_retry_harness(case, model, use_contract=False, eval_model=LEG_EVAL_MODEL)
    if condition == "retry_with_contract":
        from retry_harness import run_retry_harness
        return run_retry_harness(case, model, use_contract=True, eval_model=LEG_EVAL_MODEL)
    if condition == "retry_adaptive":
        from retry_harness import run_retry_harness
        return run_retry_harness(case, model, use_contract=False, use_adaptive=True, eval_model=LEG_EVAL_MODEL)
    if condition == "retry_alignment":
        from retry_harness import run_retry_harness
        return run_retry_harness(case, model, use_alignment=True, eval_model=LEG_EVAL_MODEL)
    if condition == "leg_reduction":
        return run_leg_reduction(case, model)
    return run_single(case, model, condition)


def run_all(cases: list[dict], model: str, conditions: list[str],
            max_workers: int = 1, quiet: bool = False) -> list[dict]:
    work = [(case, cond) for case in cases for cond in conditions]
    total = len(work)
    raw: dict[tuple[str, str], dict] = {}

    t0 = time.monotonic()

    if max_workers <= 1:
        for i, (case, cond) in enumerate(work):
            cid, cn, ev = _run_one(case, model, cond)
            raw[(cid, cn)] = ev
            if not quiet:
                _print_progress(i + 1, total, cid, cn, ev)
    else:
        if not quiet:
            print(f"  Parallel execution: {max_workers} workers, {total} calls")
        import logging as _logging
        _plog = _logging.getLogger("t3.runner")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_one, case, model, cond): (case["id"], cond)
                       for case, cond in work}
            _plog.info("POOL_SUBMITTED %d futures, max_workers=%d", len(futures), max_workers)
            done = 0
            failed = 0
            for fut in as_completed(futures):
                cid_hint, cn_hint = futures[fut]
                try:
                    cid, cn, ev = fut.result()
                except Exception as e:
                    failed += 1
                    _plog.error("TASK_EXCEPTION case=%s cond=%s: %s", cid_hint, cn_hint, e)
                    raw[(cid_hint, cn_hint)] = {
                        "pass": False, "score": 0.0,
                        "reasons": [f"task_exception: {e}"],
                        "failure_modes": [], "execution": {"status": "error", "ran": False},
                    }
                    done += 1
                    if not quiet:
                        print(f"  [{done:>3}/{total}] {cid_hint:<28} {cn_hint:<18} ERROR: {e}")
                    continue
                raw[(cid, cn)] = ev
                done += 1
                _plog.info("POOL_COMPLETED %d/%d case=%s cond=%s", done, total, cid, cn)
                if not quiet:
                    _print_progress(done, total, cid, cn, ev)
            _plog.info("POOL_ALL_DONE %d/%d completed (%d failed)", done, total, failed)
        _plog.info("POOL_SHUTDOWN executor exited cleanly")

    elapsed = time.monotonic() - t0
    if not quiet:
        print(f"\n  Completed {total} calls in {elapsed:.1f}s")

    results = []
    for case in cases:
        cid = case["id"]
        entry = {"case_id": cid, "failure_mode": case["failure_mode"]}
        for cond in conditions:
            ev = raw.get((cid, cond), {})

            # CGE INVARIANT: if condition is contract_gated, cge_executed MUST exist
            if cond == "contract_gated":
                if "cge_executed" not in ev:
                    raise RuntimeError(
                        f"CGE INTEGRITY FAILURE: contract_gated result for {cid} "
                        f"is missing 'cge_executed' field. This is a code bug."
                    )
                if ev["cge_executed"] is False:
                    ev["pass"] = False
                    ev["score"] = 0.0
                    if "CGE did not execute" not in str(ev.get("reasons", [])):
                        ev.setdefault("reasons", []).insert(
                            0, "INVALID: CGE did not execute (contract parse failed)"
                        )

            entry[cond] = {
                "pass": ev.get("pass", False),
                "score": ev.get("score", 0),
                "reasons": ev.get("reasons", []),
                "failure_modes": ev.get("failure_modes", []),
                "operator_used": ev.get("operator_used"),
                "identified_correct_issue": ev.get("identified_correct_issue", False),
                "final_output_correct": ev.get("final_output_correct", False),
                "reasoning_action_gap": ev.get("reasoning_action_gap", False),
            }
        results.append(entry)
    return results


def _print_progress(done: int, total: int, cid: str, cond: str, ev: dict):
    p = "PASS" if ev.get("pass") else "FAIL"
    s = ev.get("score", 0)
    gap = "*" if ev.get("reasoning_action_gap") else ""
    print(f"  [{done:>3}/{total}] {cid:<28} {cond:<18} {p} {s:.2f}{gap}")


# ============================================================
# PRINT RESULTS
# ============================================================

def print_results(results: list[dict], conditions: list[str], model: str):
    total = len(results)
    print(f"\n{'=' * 72}")
    print(f"  RESULTS — model={model}, {total} cases x {len(conditions)} conditions")
    print(f"{'=' * 72}")

    print(f"\n  {'Condition':<22} {'Pass':>5} {'Avg':>6} {'Gaps':>5}")
    print(f"  {'─' * 42}")
    for cond in conditions:
        n_pass = sum(1 for r in results if r.get(cond, {}).get("pass", False))
        avg = sum(r.get(cond, {}).get("score", 0) for r in results) / total
        gaps = sum(1 for r in results if r.get(cond, {}).get("reasoning_action_gap", False))
        print(f"  {cond:<22} {n_pass:>2}/{total}  {avg:>5.2f} {gaps:>4}")
    print()

    cols = [COND_LABELS.get(c, c[:2].upper()) for c in conditions]
    print(f"  {'Case':<28} " + " ".join(f"{c:>5}" for c in cols) + "  Type")
    print(f"  {'─' * (30 + 6 * len(cols))}")
    for r in results:
        scores = []
        for c in conditions:
            s = r.get(c, {}).get("score", 0)
            gap = r.get(c, {}).get("reasoning_action_gap", False)
            scores.append(f"{s:.2f}{'*' if gap else ' '}")

        bl_p = r.get("baseline", {}).get("pass", False)
        dx_p = r.get("diagnostic", {}).get("pass", False)
        gr_p = r.get("guardrail", {}).get("pass", False)
        gs_p = r.get("guardrail_strict", {}).get("pass", False)
        cf_p = r.get("counterfactual", {}).get("pass", False)
        ra_p = r.get("reason_then_act", {}).get("pass", False)

        if bl_p:
            ftype = "no failure"
        elif gs_p and not dx_p and not gr_p:
            ftype = "HARD COMMIT"
        elif (gr_p or gs_p) and not dx_p:
            ftype = "COMMITMENT"
        elif dx_p:
            ftype = "ignorance"
        elif cf_p or ra_p:
            ftype = "L3 reasoning"
        else:
            ftype = "resistant"

        print(f"  {r['case_id']:<28} " + " ".join(f"{s:>5}" for s in scores) + f"  {ftype}")

    total_gaps = sum(
        1 for r in results for c in conditions
        if r.get(c, {}).get("reasoning_action_gap", False)
    )
    if total_gaps:
        print(f"\n  * = reasoning-action gap ({total_gaps} total)")


# ============================================================
# MAIN
# ============================================================

def _run_ablation_mode(args):
    """Ablation mode: single (model, trial) run with isolated output directory."""
    import os
    import subprocess as _sp
    from execution import set_ablation_context

    run_dir = Path(args.run_dir)
    model = args.model
    trial = args.trial
    run_id = args.run_id

    conditions = [c.strip() for c in args.conditions.split(",")] if args.conditions else ALL_CONDITIONS
    for c in conditions:
        if c not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition {c!r}")

    cases = load_cases(case_id=args.case_id, cases_file=args.cases)

    # PREFLIGHT: verify every case can be evaluated BEFORE spending API calls
    preflight_verify_tests(cases)

    from condition_registry import validate_run
    validate_run(cases, conditions)

    n_calls = len(cases) * len(conditions)
    total_jobs = args.total_jobs if args.total_jobs > 0 else n_calls

    # Step 1: Create run directory
    run_dir.mkdir(parents=True, exist_ok=True)

    # Step 2: Write metadata.json immediately
    try:
        git_hash = _sp.check_output(
            ["git", "rev-parse", "HEAD"], stderr=_sp.DEVNULL
        ).decode().strip()
    except Exception:
        git_hash = "unknown"

    metadata = {
        "model": model,
        "trial": trial,
        "run_id": run_id,
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cases_file": args.cases,
        "conditions": conditions,
        "total_jobs": total_jobs,
        "command_line": sys.argv,
        "git_hash": git_hash,
    }
    metadata_path = run_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Step 3: Touch events.jsonl
    events_path = run_dir / "events.jsonl"
    events_path.touch()

    # Step 4: Set ablation context for event emission
    set_ablation_context(events_path=events_path, trial=trial, run_id=run_id)

    # Step 5: Initialize run logger
    log_path = init_run_log(model, log_dir=run_dir)

    print(f"T3 Ablation — {len(cases)} cases x {len(conditions)} conditions = {n_calls} evals")
    print(f"  Model: {model}, Trial: {trial}, Run ID: {run_id}")
    print(f"  Run dir: {run_dir}")

    # Step 6: Run evaluations sequentially (no thread pool)
    results = run_all(cases, model, conditions, max_workers=1, quiet=args.quiet)
    print_results(results, conditions, model)

    # Step 7: Verify log integrity
    from execution import get_run_logger
    logger = get_run_logger()
    valid, reason = logger.verify_integrity()
    stats = logger.get_stats()
    if valid:
        print(f"\n  Log verified: {log_path} (run_id={stats['run_id']}, {stats['attempted']} writes OK)")
    else:
        print(f"\n  RUN INVALID: {reason}")

    close_run_log()

    # Step 8: Write completion marker to metadata
    events_written = len([line for line in open(events_path) if line.strip()])
    metadata["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    metadata["events_written"] = events_written
    metadata["log_valid"] = valid
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Reset ablation context
    set_ablation_context(events_path=None, trial=None, run_id=None)


def main():
    parser = argparse.ArgumentParser(description="T3 multi-condition experiment")
    parser.add_argument("--model", default="gpt-4.1-nano")
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--cases", default="cases.json",
                        help="Path to cases JSON file (default: cases.json)")
    parser.add_argument("--conditions", default=None)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--quiet", action="store_true")
    # Legacy mode args
    parser.add_argument("--clear-events", action="store_true",
                        help="Clear events.jsonl before this run (legacy mode)")
    parser.add_argument("--total-jobs", type=int, default=0,
                        help="Expected eval calls for this run")
    # Ablation mode args
    parser.add_argument("--trial", type=int, default=None,
                        help="Trial number (ablation mode)")
    parser.add_argument("--run-dir", default=None,
                        help="Isolated output directory (ablation mode)")
    parser.add_argument("--run-id", default=None,
                        help="Unique run ID (ablation mode)")
    args = parser.parse_args()

    # Route to ablation mode if --run-dir is provided
    if args.run_dir is not None:
        if args.trial is None:
            raise ValueError("--trial is required in ablation mode (--run-dir provided)")
        if args.run_id is None:
            raise ValueError("--run-id is required in ablation mode (--run-dir provided)")
        _run_ablation_mode(args)
        return

    # Legacy mode (unchanged)
    conditions = [c.strip() for c in args.conditions.split(",")] if args.conditions else ALL_CONDITIONS
    for c in conditions:
        if c not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition {c!r}")

    cases = load_cases(case_id=args.case_id, cases_file=args.cases)

    # PREFLIGHT: verify every case can be evaluated BEFORE spending API calls
    preflight_verify_tests(cases)

    # PREFLIGHT: verify every (case, condition) pair is compatible
    from condition_registry import validate_run
    validate_run(cases, conditions)

    n_calls = len(cases) * len(conditions)

    # Initialize per-run log file
    log_path = init_run_log(args.model)

    # Start live metrics dashboard (legacy — uses old thread-based path for backward compat)
    # In ablation mode, dashboard is a separate process (scripts/update_dashboards.py)
    try:
        # Try to import legacy functions — they may not exist after rewrite
        from live_metrics import emit_event  # noqa: F401
        # Legacy dashboard not available in new architecture — skip
    except ImportError:
        pass

    dashboard_total = args.total_jobs if args.total_jobs > 0 else n_calls

    print(f"T3 Experiment — {len(cases)} cases x {len(conditions)} conditions = {n_calls} LLM calls")
    print(f"  Model: {args.model}")
    print(f"  Parallel: {args.parallel}")
    print(f"  Log: {log_path}")

    results = run_all(cases, args.model, conditions,
                      max_workers=args.parallel, quiet=args.quiet)
    print_results(results, conditions, args.model)

    # Verify log integrity — failed writes INVALIDATE the run
    from execution import get_run_logger
    logger = get_run_logger()
    valid, reason = logger.verify_integrity()
    stats = logger.get_stats()
    if valid:
        print(f"\n  Log verified: {log_path} (run_id={stats['run_id']}, {stats['attempted']} writes OK)")
    else:
        print(f"\n  RUN INVALID: {reason}")
        print(f"  Log: {log_path}")
        print(f"  This run's data should NOT be used for analysis.")

    # Close log to prevent bleed if another model runs in the same process
    close_run_log()


if __name__ == "__main__":
    main()
