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

from execution import (
    build_prompt, run_single, run_repair_loop, run_contract_gated,
    run_leg_reduction,
    init_run_log, close_run_log, get_current_log_path, get_log_write_stats,
)
from constants import ALL_CONDITIONS, VALID_CONDITIONS, COND_LABELS, RETRY_CONDITIONS

BASE_DIR = Path(__file__).parent

def get_eval_model() -> str:
    """Get evaluator model from config. No hardcoded fallback."""
    from experiment_config import get_config
    return get_config().models.evaluator.name

COND_DESCRIPTIONS = [
    "baseline",
    "diagnostic",
    "guardrail",
    "guardrail_strict",
    "counterfactual",
    "reason_then_act",
    "self_check",
    "counterfactual_check",
    "test_driven",
    "repair_loop",
    "scm_descriptive",
    "scm_constrained",
    "scm_constrained_evidence",
    "scm_constrained_evidence_minimal",
    "evidence_only",
    "length_matched_control",
    "structured_reasoning",
    "free_form_reasoning",
    "branching_reasoning",
    "contract_gated",
    "retry_no_contract",
    "retry_with_contract",
    "retry_adaptive",
    "retry_alignment",
    "leg_reduction"
]

REPAIR_LOOP_MAX_ATTEMPTS = 2

# Canonical imports are from execution.py. No aliases.


# ============================================================
# LOAD CASES
# ============================================================

def load_cases(case_id: str, cases_file: str) -> list[dict]:
    cases_path = BASE_DIR / cases_file
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    for case in cases:
        code_files = {}
        for rel_path in case["code_files"]:
            full_path = BASE_DIR / rel_path
            content = full_path.read_text(encoding="utf-8").strip()
            assert content, (
                f"PREFLIGHT: Empty file {rel_path} in case {case['id']}. "
                f"Empty files are not allowed in the benchmark."
            )
            code_files[rel_path] = content
        case["code_files_contents"] = code_files
        validate_import_consistency(case)
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise ValueError(f"No case with id={case_id!r}")
    return cases


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
# RUN ALL — serial execution only
# ============================================================
# Parallelism is handled at the PROCESS level (e.g., shell scripts
# launching separate runner.py processes per model/trial).
# No threads. No ThreadPoolExecutor. No shared mutable state.

def _run_one(case: dict, model: str, condition: str) -> tuple[str, str, dict]:
    cid = case["id"]
    _log = __import__("logging").getLogger("t3.runner")
    _log.info("TASK_START case=%s cond=%s", cid, condition)
    t0 = __import__("time").monotonic()
    try:
        result = _run_one_inner(case, model, condition)
        elapsed = __import__("time").monotonic() - t0
        _log.info("TASK_END case=%s cond=%s elapsed=%.1fs pass=%s",
                   cid, condition, elapsed, result[2].get("pass"))
        return result
    except Exception as e:
        elapsed = __import__("time").monotonic() - t0
        _log.error("TASK_FAILED case=%s cond=%s elapsed=%.1fs error=%s",
                    cid, condition, elapsed, e)
        raise


def _run_one_inner(case: dict, model: str, condition: str) -> tuple[str, str, dict]:
    if condition == "repair_loop":
        return run_repair_loop(case, model)
    if condition == "contract_gated":
        return run_contract_gated(case, model)
    if condition in RETRY_CONDITIONS and condition != "repair_loop":
        from retry_harness import run_retry_harness
        return run_retry_harness(case, model, condition=condition, eval_model=get_eval_model())
    if condition == "leg_reduction":
        return run_leg_reduction(case, model)
    return run_single(case, model, condition)


def run_all(cases: list[dict], model: str, conditions: list[str],
            quiet: bool = False) -> list[dict]:
    """Run all (case, condition) pairs sequentially. No threads.

    Parallelism is achieved by launching multiple runner.py processes
    externally (e.g., one per model/trial in a shell script).
    """
    work = [(case, cond) for case in cases for cond in conditions]
    total = len(work)
    raw: dict[tuple[str, str], dict] = {}

    t0 = time.monotonic()

    for i, (case, cond) in enumerate(work):
        cid, cn, ev = _run_one(case, model, cond)
        raw[(cid, cn)] = ev
        if not quiet:
            _print_progress(i + 1, total, cid, cn, ev)

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
    destroys metadata (no end_time) without saving any data.
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
    # The data is already persisted — crashing here only destroys metadata.
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
        warnings.append(
            f"SANITY WARNING: all {total} evals failed. Zero passes."
        )

    for w in warnings:
        _guard_log.warning(w)
        print(f"  [!] {w}")


def create_run_timestamp_dir(run_dir: Path) -> Path:
    """Create a timestamp subdirectory inside run_dir. Called ONCE per run.

    Format: YYYY-MM-DD_HH-MM-SS (sortable, human-readable).
    Fails loudly if directory creation fails. Never recompute — call once,
    pass the result to all downstream writers.

    Returns the Path to the created timestamp directory.
    """
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    ts_dir = run_dir / timestamp
    ts_dir.mkdir(parents=True, exist_ok=False)
    return ts_dir


def run_ablation_mode(args):
    """Ablation mode: single (model, trial) run with isolated output directory."""
    import os
    import subprocess as _sp
    from execution import set_ablation_context

    # All run parameters come from config — the single source of truth
    from experiment_config import get_config as _get_config
    _cfg = _get_config()
    run_dir = Path(_cfg.run.run_dir)
    trial = _cfg.run.trial
    run_id = _cfg.run.run_id
    model = _cfg.models.generation[0].name

    # Conditions and cases come from config ONLY — never from CLI in ablation mode
    from experiment_config import get_config
    conditions = list(get_config().conditions.keys())
    for c in conditions:
        if c not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition {c!r} in config")

    cases_file = get_config().cases.source
    cases = load_cases(case_id=args.case_id, cases_file=cases_file)

    # Limit cases for smoke tests
    if args.max_cases and args.max_cases > 0:
        cases = cases[:args.max_cases]

    # PREFLIGHT: verify every case can be evaluated BEFORE spending API calls
    preflight_verify_tests(cases)

    from condition_registry import validate_run
    validate_run(cases, conditions)

    # PREFLIGHT: config sanity
    validate_experiment_config(cases, conditions, model)

    n_calls = len(cases) * len(conditions)
    total_jobs = args.total_jobs if args.total_jobs > 0 else n_calls

    # Step 1: Create run directory and timestamp subdirectory
    run_dir.mkdir(parents=True, exist_ok=True)
    ts_dir = create_run_timestamp_dir(run_dir)

    # All outputs go into ts_dir from here on
    output_dir = ts_dir

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
        "timestamp_dir": ts_dir.name,
        "cases_file": cases_file,
        "conditions": conditions,
        "total_jobs": total_jobs,
        "command_line": sys.argv,
        "git_hash": git_hash,
    }
    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Step 3: Touch events.jsonl
    events_path = output_dir / "events.jsonl"
    events_path.touch()

    # Step 4: Set ablation context for event emission
    set_ablation_context(events_path=events_path, trial=trial, run_id=run_id)

    # Step 4.5: Initialize call-level logger
    from call_logger import init_call_logger, close_call_logger
    init_call_logger(output_dir)

    # Step 5: Initialize run logger
    log_path = init_run_log(model, log_dir=output_dir)

    print(f"T3 Ablation — {len(cases)} cases x {len(conditions)} conditions = {n_calls} evals")
    print(f"  Model: {model}, Trial: {trial}, Run ID: {run_id}")
    print(f"  Run dir: {run_dir}")
    print(f"  Output:  {output_dir}")

    # Step 6: Run evaluations sequentially
    results = run_all(cases, model, conditions, quiet=args.quiet)
    print_results(results, conditions, model)

    # Step 6.5: Execution sanity + result distribution guard
    validate_execution_sanity(results, conditions)

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

    # Step 7.5: Close call logger and record count
    from call_logger import close_call_logger, get_call_count
    total_calls = close_call_logger()
    print(f"  Call log: {total_calls} LLM calls logged to {output_dir}/calls/")

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
    parser = argparse.ArgumentParser(description="T3 ablation experiment runner")
    parser.add_argument("--config", default="configs/default.yaml",
                        help="Path to experiment YAML config (single source of truth)")
    parser.add_argument("--case-id", default=None,
                        help="Filter to a single case by ID")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None,
                        help="Limit number of cases (for smoke tests)")
    # Kept for detection — hard-fail if used
    parser.add_argument("--model", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cases", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--conditions", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--trial", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--run-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--total-jobs", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    # ── ENFORCE: config is the single source of truth ──
    _config_only_flags = {
        "--model": args.model, "--cases": args.cases, "--conditions": args.conditions,
        "--trial": args.trial, "--run-dir": args.run_dir, "--run-id": args.run_id,
    }
    violations = [flag for flag, val in _config_only_flags.items() if val is not None]
    if violations:
        raise ValueError(
            f"ERROR: {', '.join(violations)} cannot be set via CLI. "
            f"All run parameters come from the config YAML (--config). "
            f"Edit the config file to change these values."
        )

    # ── LOAD CONFIG (single source of truth) ──
    from experiment_config import load_config
    config = load_config(args.config)

    print(f"CONFIG LOADED: {args.config} (sha={config._config_sha256})")
    print(f"  Evaluator model: {config.models.evaluator.name}")
    print(f"  Generation models: {[m.name for m in config.models.generation]}")
    print(f"  Conditions: {list(config.conditions.keys())}")
    print(f"  Output format: {config.execution.output_format}")
    print(f"  Run: trial={config.run.trial}, run_id={config.run.run_id}, run_dir={config.run.run_dir}")

    # ── SINGLE EXECUTION PATH ──
    run_ablation_mode(args)


if __name__ == "__main__":
    main()
