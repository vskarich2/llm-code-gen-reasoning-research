# ============================================================
# T3 Code Generation — Multi-Condition Experiment Runner
#
# Run:  python runner.py
#       python runner.py --model gpt-4o-mini
#       python runner.py --case-id l3_state_pipeline
#       python runner.py --conditions baseline,diagnostic
#       (parallelism via separate processes, not --parallel flag)
# ============================================================

import argparse
import json
import sys
import time
from pathlib import Path

from core.config.constants import VALID_CONDITIONS, COND_LABELS, V2_CONDITIONS

from core.config.paths import PROJECT_ROOT
BASE_DIR = PROJECT_ROOT


# Legacy: kept for test backward compatibility
COND_DESCRIPTIONS = [
    "baseline", "diagnostic", "guardrail", "guardrail_strict",
    "counterfactual", "reason_then_act", "self_check", "counterfactual_check",
    "test_driven", "repair_loop", "scm_descriptive", "scm_constrained",
    "scm_constrained_evidence", "scm_constrained_evidence_minimal",
    "evidence_only", "length_matched_control", "structured_reasoning",
    "free_form_reasoning", "branching_reasoning", "contract_gated",
    "retry_no_contract", "retry_with_contract", "retry_adaptive", "retry_alignment",
    "leg_reduction",
]

# Canonical imports are from execution.py. No aliases.


# ============================================================
# LOAD CASES
# ============================================================



def validate_import_consistency(case: dict) -> None:
    """Preflight: verify case files have consistent, supported import structure.

    Checks:
    1. All files in same directory
    2. No duplicate basenames
    3. All cross-file imports are flat sibling style (no relative, no package-qualified)
    """
    import ast
    from collections import Counter

    file_paths = case["code_files"]
    cid = case["id"]

    # CHECK 1: All files in same directory
    parents = set(str(Path(f).parent) for f in file_paths)
    assert len(parents) == 1, (
        f"Case {cid}: files span multiple directories: {parents}. "
        f"Benchmark requires all case files in a single directory."
    )

    # CHECK 2: No duplicate basenames
    basenames = [Path(f).name for f in file_paths]
    dupes = [b for b, c in Counter(basenames).items() if c > 1]
    assert not dupes, (
        f"Case {cid}: duplicate basenames: {dupes}. "
        f"Flat sibling imports require unique basenames."
    )

    # CHECK 3: All cross-file imports are flat sibling style
    sibling_modules = {Path(f).stem for f in file_paths}
    for rel_path in file_paths:
        content = case["code_files_contents"].get(rel_path, "")
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue  # syntax errors are caught later in the pipeline
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    raise ValueError(
                        f"Case {cid}: {rel_path} uses relative import "
                        f"(level={node.level}). Not supported by benchmark."
                    )
                if node.module and "." in node.module:
                    base = node.module.split(".")[0]
                    if base in sibling_modules:
                        raise ValueError(
                            f"Case {cid}: {rel_path} uses qualified import "
                            f"'from {node.module} import ...'. "
                            f"Use flat sibling import instead."
                        )


def preflight_verify_tests(cases: list[dict]) -> None:
    """Verify every case has a resolvable test function BEFORE running.

    If any case cannot be evaluated, the experiment MUST NOT proceed.
    Partial execution of unsupported cases is forbidden.
    """
    from core.pipeline.execution.test_loader import _load_v2_test

    missing = []
    for case in cases:
        cid = case["id"]
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
# RUN ALL — serial execution only
# ============================================================
# Parallelism is handled at the PROCESS level (e.g., shell scripts
# launching separate runner.py processes per model/trial).
# No threads. No ThreadPoolExecutor. No shared mutable state.


def _run_one(case: dict, model: str, condition: str, logger) -> tuple[str, str, dict]:
    cid = case["id"]
    _log = __import__("logging").getLogger("t3.runner")
    _log.info("TASK_START case=%s cond=%s", cid, condition)
    t0 = __import__("time").monotonic()

    # Start case trace — returns CaseHandle(trace_id, event_id)
    handle = logger.start_case(cid)

    try:
        result = _run_one_inner(case, model, condition, logger, handle.event_id)
        elapsed = __import__("time").monotonic() - t0
        _log.info(
            "TASK_END case=%s cond=%s elapsed=%.1fs pass=%s",
            cid, condition, elapsed, result[2].get("pass"),
        )
        return result
    except Exception as e:
        import traceback as _tb
        elapsed = __import__("time").monotonic() - t0
        _log.error("TASK_FAILED case=%s cond=%s elapsed=%.1fs error=%s", cid, condition, elapsed, e)
        logger.log_structured_error("case.error.exception", cid, {
            "exception_type": type(e).__name__,
            "error": str(e),
            "traceback_summary": _tb.format_exc()[-500:],
        })
        logger.fail_case(cid, f"{type(e).__name__}: {e}",
                         condition=condition, parent_event_id=handle.event_id)
        raise


def _run_one_inner(case: dict, model: str, condition: str, logger,
                    case_start_eid: int | str) -> tuple[str, str, dict]:
    # HARD GUARD: only v2 conditions are allowed
    if condition not in V2_CONDITIONS:
        raise RuntimeError(
            f"FATAL: Legacy condition '{condition}' attempted. "
            f"Only V2 conditions are allowed: {sorted(V2_CONDITIONS)}"
        )

    if condition in ("baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2",
                     "baseline_v3", "leg_reduction_lean_v3"):
        from core.pipeline.orchestration.execution_v2 import run_v2
        return run_v2(case, model, condition, logger, case_start_eid)
    if condition.startswith("retry_"):
        from core.pipeline.orchestration.retry_v2 import run_retry_v2
        return run_retry_v2(case, model, condition, logger, case_start_eid)
    if condition.startswith("critique_"):
        # V3 critique conditions route through retry with critique variant
        from core.pipeline.orchestration.retry_v2 import run_retry_v2
        return run_retry_v2(case, model, condition, logger, case_start_eid)

    raise RuntimeError(
        f"FATAL: V2 condition '{condition}' has no dispatch handler"
    )


def run_all(
    cases: list[dict], model: str, conditions: list[str], logger,
    quiet: bool = False, skip: set | None = None,
) -> list[dict]:
    """Run all (case, condition) pairs sequentially. No threads.

    Args:
        logger: RunLogger instance. Required. Passed to every execution function.
        skip: set of (case_id, condition) tuples to skip (already completed).
    """
    if logger is None:
        raise RuntimeError("run_all requires an explicit logger")
    work = [(case, cond) for case in cases for cond in conditions]
    total = len(work)
    raw: dict[tuple[str, str], dict] = {}
    skipped = 0
    cases_completed = 0
    _last_heartbeat = time.monotonic()

    t0 = time.monotonic()

    for i, (case, cond) in enumerate(work):
        if skip and (case["id"], cond) in skip:
            skipped += 1
            if not quiet:
                print(f"  [{i+1:3d}/{total}] {case['id']:30s} {cond:18s} SKIPPED (already completed)")
            continue
        cid, cn, ev = _run_one(case, model, cond, logger)
        raw[(cid, cn)] = ev
        cases_completed += 1
        if not quiet:
            _print_progress(i + 1, total, cid, cn, ev)

        # Heartbeat: write every 30s if identity fields are set
        if (logger._work_id is not None
                and time.monotonic() - _last_heartbeat > 30):
            from core.logging_.logging_core import write_json_atomic
            from core.config.paths import HEARTBEAT_FILENAME
            write_json_atomic(logger._run_dir / HEARTBEAT_FILENAME, {
                "work_id": logger._work_id,
                "instance_id": logger._instance_id,
                "pid": __import__("os").getpid(),
                "updated_at": __import__("datetime").datetime.now().isoformat(),
                "current_case_id": cid,
                "cases_completed": cases_completed,
                "sequence": logger._sequence,
            })
            _last_heartbeat = time.monotonic()

    elapsed = time.monotonic() - t0
    ran = total - skipped
    if not quiet:
        msg = f"\n  Completed {ran} calls in {elapsed:.1f}s"
        if skipped:
            msg += f" ({skipped} skipped via --resume)"
        print(msg)

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
        1 for r in results for c in conditions if r.get(c, {}).get("reasoning_action_gap", False)
    )
    if total_gaps:
        print(f"\n  * = reasoning-action gap ({total_gaps} total)")


# ============================================================
# MAIN
# ============================================================


def validate_experiment_config(cases, conditions, model):
    """Validate experiment configuration before spending API calls."""
    if len(cases) < 5 and not any(c["id"] == "alias_config_a" for c in cases[:3]):
        # Allow small case sets for smoke tests if canary is present
        pass
    if not conditions:
        raise RuntimeError("CONFIG ERROR: empty conditions list")
    if len(set(conditions)) != len(conditions):
        raise RuntimeError(f"CONFIG ERROR: duplicate conditions: {conditions}")
    case_ids = [c["id"] for c in cases]
    if len(set(case_ids)) != len(case_ids):
        dupes = [cid for cid in set(case_ids) if case_ids.count(cid) > 1]
        raise RuntimeError(f"CONFIG ERROR: duplicate case IDs: {dupes}")
    for c in cases:
        if not c.get("code_files"):
            raise RuntimeError(f"CONFIG ERROR: case {c['id']} has no code_files")


def validate_execution_sanity(results, conditions):
    """Post-run validation: execution sanity + result distribution guard.

    WARNS on suspicious distributions but does NOT crash the run.
    Data is already written to events.jsonl/run.jsonl — crashing here
    destroys metadata (no end_time) without saving any case_data.
    """
    import logging as _logging

    _guard_log = _logging.getLogger("t3.runner.sanity")
    from collections import Counter

    total = 0
    ran_count = 0
    pass_count = 0
    categories = Counter()

    for r in results:
        for cond in conditions:
            ev = r.get(cond, {})
            total += 1
            if ev.get("score", 0) > 0 or ev.get("pass"):
                ran_count += 1
            if ev.get("pass"):
                pass_count += 1
            cat = "pass" if ev.get("pass") else "fail"
            categories[cat] += 1

    if total == 0:
        return

    ran_rate = ran_count / total
    pass_rate = pass_count / total

    # All guards now WARN instead of crashing.
    # The case_data is already persisted — crashing here only destroys metadata.
    warnings = []

    if ran_rate < 0.5 and total >= 10:
        warnings.append(
            f"SANITY WARNING: ran_rate={ran_rate:.1%} < 50%. "
            f"Only {ran_count}/{total} evals executed code."
        )

    if pass_rate == 0 and total >= 10:
        warnings.append(
            f"SANITY WARNING: 0% pass rate across {total} evals. "
            f"Distribution: {dict(categories)}."
        )

    if categories.get("fail", 0) == total and total >= 10:
        warnings.append(f"SANITY WARNING: all {total} evals failed. Zero passes.")

    for w in warnings:
        _guard_log.warning(w)
        print(f"  [!] {w}")


_TERMINAL_EVENT_TYPES = frozenset({"case.end", "case.failed"})


def load_completed_pairs(events_path: Path) -> set:
    """Read events.jsonl and return set of completed (case_id, condition) pairs.

    Completion semantics:
      - case.end   → completed (success). Pair is skipped on resume.
      - case.failed → completed (failure). Pair is skipped on resume.
        Failed cases are not re-run automatically. Use --rerun-failed
        or delete the events file to force re-execution.

    A pair is complete ONLY if a terminal event exists. Non-terminal
    events (case.start, call.*, etc.) do NOT count.

    Integrity CLAUDE_RULES:
      - Corrupt JSON is tolerated ONLY on the final line (partial write
        from crash). Corruption on any other line raises RuntimeError.
      - Terminal events missing case_id or condition raise RuntimeError.
      - Duplicate terminal events for the same pair raise RuntimeError.
    """
    completed = set()
    if not events_path.exists():
        return completed
    lines = events_path.read_text().splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break  # truncated final line from crash — tolerated
            raise RuntimeError(
                f"Corrupt JSON at line {i + 1} in {events_path}. "
                f"Only the final line may be truncated. "
                f"Data integrity violation — inspect events.jsonl."
            )
        et = event.get("event_type", "")
        if et not in _TERMINAL_EVENT_TYPES:
            continue
        cid = event.get("case_id")
        cond = event.get("condition")
        if not cid or not cond:
            raise RuntimeError(
                f"Malformed terminal event at line {i + 1} in {events_path}: "
                f"event_type={et!r} but case_id={cid!r}, condition={cond!r}. "
                f"Terminal events must have both fields."
            )
        pair = (cid, cond)
        if pair in completed:
            raise RuntimeError(
                f"Duplicate terminal event for ({cid}, {cond}) at line {i + 1} "
                f"in {events_path}. Data integrity violation."
            )
        completed.add(pair)
    return completed


def create_run_timestamp_dir(run_dir: Path, run_id: str = "") -> Path:
    """Create a uniquely-named subdirectory inside run_dir. Called ONCE per run.

    Format: YYYY-MM-DD_HH-MM-SS_{run_id} (sortable, collision-free).
    Fails loudly if directory creation fails.

    Returns the Path to the created directory.
    """
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    name = f"{timestamp}_{run_id}" if run_id else timestamp
    ts_dir = run_dir / name
    ts_dir.mkdir(parents=True, exist_ok=False)
    return ts_dir


def run_ablation_mode(args):
    """Run a single (model, trial) experiment.

    FILESYSTEM CONTRACT: config.run.run_dir is the final, resolved output
    directory. This function writes ONLY into that directory. It creates
    NO subdirectories. All directory structure is owned upstream
    (main for standalone, orchestrator for multi-worker).
    """
    import os
    import subprocess as _sp
    from core.logging_.logging_core import RunLogger

    # All run parameters come from config — the single source of truth
    from core.config.experiment_config import get_config as _get_config

    _cfg = _get_config()
    run_dir = Path(_cfg.run.run_dir)
    trial = _cfg.run.trial
    run_id = _cfg.run.run_id
    model = _cfg.models.generation[0].name

    from core.config.experiment_config import get_config

    conditions = list(get_config().conditions.keys())
    for c in conditions:
        if c not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition {c!r} in config")

    cases_file = get_config().cases.source
    from core.pipeline.orchestration.shared import load_cases
    cases = load_cases(case_id=args.case_id, cases_file=cases_file)

    # Apply case_ids filter from config (set by orchestrator for per-case work items)
    cfg_case_ids = getattr(get_config().cases, "case_ids", None)
    if cfg_case_ids:
        case_id_set = set(cfg_case_ids)
        cases = [c for c in cases if c["id"] in case_id_set]

    if args.max_cases and args.max_cases > 0:
        cases = cases[: args.max_cases]

    preflight_verify_tests(cases)

    from core.registry.condition_registry import validate_run
    validate_run(cases, conditions)

    validate_experiment_config(cases, conditions, model)

    n_calls = len(cases) * len(conditions)

    # run_dir IS the final output directory. No subdirectory creation.
    output_dir = run_dir

    # Resume skip set: populated by main() for standalone --resume.
    # Orchestrator retries use fresh attempt dirs — no skip needed.
    skip = None
    if getattr(args, "resume", None):
        events_path = output_dir / "events.jsonl"
        if events_path.exists():
            skip = load_completed_pairs(events_path)
            if skip:
                print(f"RESUMING: {output_dir} — {len(skip)} completed pairs found")

    # Step 2: Create RunLogger — the ONLY logger for this run.
    # condition=None because this runner handles multiple conditions.
    # Condition is set per-event via the condition parameter.
    try:
        from core.config.experiment_config import get_config as _gc
        _exp_name = _gc().experiment.name
    except Exception:
        _exp_name = None

    # Read orchestrator identity fields from config (None in standalone mode)
    _work_id = _cfg._work_id
    _instance_id = _cfg._instance_id
    _attempt = _cfg._attempt

    logger = RunLogger(
        run_dir=output_dir,
        run_id=run_id,
        model=model,
        condition=None,
        trial=trial,
        experiment_name=_exp_name,
        work_id=_work_id,
        instance_id=_instance_id,
        attempt=_attempt,
    )

    # Step 3-6: Run with guaranteed finalize.
    # Exception policy:
    #   - If body raises: finalize is attempted, original exception re-raised.
    #   - If finalize raises after body success: finalize exception propagates.
    #   - If finalize raises after body failure: finalize exception is logged,
    #     original exception re-raised (original is not masked).
    primary_exception = None
    try:
        try:
            git_hash = (
                _sp.check_output(["git", "rev-parse", "HEAD"], stderr=_sp.DEVNULL).decode().strip()
            )
        except Exception:
            git_hash = "unknown"

        logger.log_event("run.start", {
            "total_cases": len(cases),
            "conditions": conditions,
            "cases_file": cases_file,
            "model": model,
            "trial": trial,
            "git_hash": git_hash,
            "command_line": sys.argv,
        }, phase="run")

        logger.log_lifecycle_event("worker.start", {
            "pid": os.getpid(),
            "config_sha256": _cfg._config_sha256,
            "case_ids": [c["id"] for c in cases],
        })

        remaining = n_calls - (len(skip) if skip else 0)
        print(f"T3 Ablation — {len(cases)} cases x {len(conditions)} conditions = {n_calls} evals")
        if skip:
            print(f"  Resuming: {len(skip)} already done, {remaining} remaining")
        print(f"  Model: {model}, Trial: {trial}, Run ID: {run_id}")
        print(f"  Run dir: {run_dir}")
        print(f"  Output:  {output_dir}")

        _t0_run = time.monotonic()
        results = run_all(cases, model, conditions, logger, quiet=args.quiet, skip=skip)
        _elapsed_run = time.monotonic() - _t0_run
        print_results(results, conditions, model)

        validate_execution_sanity(results, conditions)

        _total_cases = len(results)
        _pass_count = sum(
            1 for r in results for c in conditions if r.get(c, {}).get("pass")
        )
        _fail_count = sum(
            1 for r in results for c in conditions if not r.get(c, {}).get("pass")
        )
        logger.log_lifecycle_event("worker.end", {
            "completed_cases": _total_cases,
            "failed_cases": _fail_count,
            "pass_rate": round(_pass_count / max(_total_cases * len(conditions), 1), 4),
            "elapsed_seconds": round(_elapsed_run, 2),
        })

        logger.log_event("run.end", {
            "total_cases": len(cases),
            "total_evals": n_calls,
        }, phase="run")

    except Exception as e:
        primary_exception = e
        # Best-effort: log run.failed event before finalize
        try:
            logger.log_event("run.failed", {
                "error": f"{type(e).__name__}: {e}",
            }, phase="run")
        except Exception:
            pass  # Cannot log — finalize will still run

    finally:
        try:
            stats = logger.finalize()
            if primary_exception is None:
                print(f"\n  Run complete: pass_rate={stats['pass_rate']:.1%} ({stats['total_cases']} cases)")
                print(f"  Output: {output_dir}")
        except Exception as finalize_exc:
            if primary_exception is not None:
                # Don't mask the original exception
                logging.getLogger("t3.runner").error(
                    "finalize() failed AFTER primary exception: %s", finalize_exc)
                raise primary_exception from finalize_exc
            raise

    if primary_exception is not None:
        raise primary_exception


def main():
    parser = argparse.ArgumentParser(description="T3 ablation experiment runner")
    parser.add_argument(
        "--config",
        default="config_storage/default.yaml",
        help="Path to experiment YAML config (single source of truth)",
    )
    parser.add_argument("--case-id", default=None, help="Filter to a single case by ID")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--max-cases", type=int, default=None, help="Limit number of cases (for smoke tests)"
    )
    parser.add_argument(
        "--resume", default=None, metavar="TIMESTAMP_DIR",
        help="Resume a previous run. Pass the timestamp directory name (e.g. 2026-03-28_16-37-43). "
             "Reads existing events.jsonl to skip completed (case_id, condition) pairs."
    )
    # Kept for detection — hard-fail if used
    parser.add_argument("--model", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cases", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--conditions", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--trial", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--run-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--total-jobs", type=int, default=0, help=argparse.SUPPRESS)
    # Orchestrator passes --instance-id for PID verification. No-op in runner logic.
    parser.add_argument("--instance-id", default=None, help=argparse.SUPPRESS)
    # Orchestrator flags passed through for dispatch
    parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rerun-failed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--kill-orphans", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force-lock-recovery", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rebuild-merged", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # ── ENFORCE: config is the single source of truth ──
    _config_only_flags = {
        "--model": args.model,
        "--cases": args.cases,
        "--conditions": args.conditions,
        "--trial": args.trial,
        "--run-dir": args.run_dir,
        "--run-id": args.run_id,
    }
    violations = [flag for flag, val in _config_only_flags.items() if val is not None]
    if violations:
        raise ValueError(
            f"ERROR: {', '.join(violations)} cannot be set via CLI. "
            f"All run parameters come from the config YAML (--config). "
            f"Edit the config file to change these values."
        )

    # ── LOAD CONFIG (single source of truth) ──
    from core.config.experiment_config import load_config

    config = load_config(args.config)

    print(f"CONFIG LOADED: {args.config} (sha={config._config_sha256})")
    print(f"  Evaluator model: {config.models.evaluator.name}")
    print(f"  Generation models: {[m.name for m in config.models.generation]}")
    print(f"  Conditions: {list(config.conditions.keys())}")
    print(f"  Output format: {config.execution.output_format}")
    print(
        f"  Run: trial={config.run.trial}, run_id={config.run.run_id}, run_dir={config.run.run_dir}"
    )
    print(
        f"  Execution: num_workers={config.execution.num_workers}, "
        f"timeout={config.execution.worker_timeout_seconds}s, "
        f"grace={config.execution.worker_graceful_shutdown_seconds}s, "
        f"subprocess_timeout={config.execution.subprocess_timeout}s"
    )

    # ── RESOLVE OUTPUT DIRECTORY ──
    # Directory structure is owned HERE (main) and by orchestrator.
    # Runner (run_ablation_mode) writes ONLY into config.run.run_dir.
    # It creates NO subdirectories. All resolution happens below.
    if config.trials > 1 or config.execution.num_workers > 1:
        # Orchestrator path — orchestrator owns directory structure.
        from core.pipeline.orchestration.orchestrate import run_experiment
        exit_code = run_experiment(config, args)
        sys.exit(exit_code)

    # Standalone path — resolve final output directory before runner.
    # Orchestrator-spawned workers have _work_id set and run_dir pre-resolved.
    if config._work_id is None:
        run_dir = Path(config.run.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        if args.resume:
            output_dir = run_dir / args.resume
            if not output_dir.exists():
                raise RuntimeError(
                    f"--resume directory does not exist: {output_dir}\n"
                    f"Available: {sorted(p.name for p in run_dir.iterdir() if p.is_dir())}"
                )
            if not (output_dir / "events.jsonl").exists():
                raise RuntimeError(f"--resume directory has no events.jsonl: {output_dir}")
        else:
            output_dir = create_run_timestamp_dir(run_dir, run_id=config.run.run_id)
        config.run.run_dir = str(output_dir)

    run_ablation_mode(args)


if __name__ == "__main__":
    main()
