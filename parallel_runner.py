"""Simple process-parallel runner for T3 ablation experiments.

Splits cases into N chunks, launches N independent runner.py subprocesses,
merges event logs after all workers finish.

Each worker uses the existing serial pipeline unchanged. This module is
a thin orchestration layer, not a rewrite.

Usage (via runner.py):
    Set execution.num_workers > 1 in the config YAML.
    runner.py delegates to run_parallel() automatically.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from glob import glob
from pathlib import Path

import yaml


def _split_cases(cases: list[dict], n: int) -> list[list[dict]]:
    """Split case list into n roughly equal chunks."""
    chunks = [[] for _ in range(n)]
    for i, case in enumerate(cases):
        chunks[i % n].append(case)
    return [c for c in chunks if c]


def _write_chunk_config(
    base_config_path: str,
    chunk_cases_path: str,
    chunk_run_dir: str,
    chunk_run_id: str,
    tmp_dir: str,
    chunk_index: int,
) -> str:
    """Write a temporary config YAML for one chunk worker."""
    with open(base_config_path) as f:
        cfg = yaml.safe_load(f)

    cfg["cases"]["source"] = chunk_cases_path
    cfg["cases"]["max_cases"] = 0
    cfg["run"]["run_dir"] = chunk_run_dir
    cfg["run"]["run_id"] = chunk_run_id
    cfg["execution"]["num_workers"] = 1

    chunk_config_path = os.path.join(tmp_dir, f"chunk_{chunk_index}.yaml")
    with open(chunk_config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
    return chunk_config_path


def _launch_workers(
    chunk_configs: list[str],
    stagger_seconds: float,
    log_dir: Path,
) -> list[tuple[subprocess.Popen, "open", "open"]]:
    """Launch worker subprocesses with staggered start.

    Returns list of (proc, stdout_file_handle, stderr_file_handle).
    Caller MUST close file handles after proc.wait().
    """
    python = sys.executable
    procs = []
    for i, config_path in enumerate(chunk_configs):
        if i > 0 and stagger_seconds > 0:
            time.sleep(stagger_seconds)
        stdout_path = log_dir / f"worker_{i}_stdout.log"
        stderr_path = log_dir / f"worker_{i}_stderr.log"
        stdout_f = open(stdout_path, "w")
        stderr_f = open(stderr_path, "w")
        cmd = [python, "runner.py", "--config", config_path]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        print(f"  Worker {i} launched (pid={proc.pid})")
        procs.append((proc, stdout_f, stderr_f))
    return procs


def _wait_for_workers(
    procs: list[tuple[subprocess.Popen, "open", "open"]],
) -> list[dict]:
    """Wait for all workers. Close file handles. Return exit info."""
    results = []
    for i, (proc, stdout_f, stderr_f) in enumerate(procs):
        proc.wait()
        # FIX 6: close file handles
        stdout_f.close()
        stderr_f.close()
        stderr_tail = ""
        try:
            stderr_tail = Path(stderr_f.name).read_text()[-500:]
        except Exception:
            pass
        results.append({
            "chunk_index": i,
            "exit_code": proc.returncode,
            "stdout_log": stdout_f.name,
            "stderr_log": stderr_f.name,
            "stderr_tail": stderr_tail,
        })
        status = "OK" if proc.returncode == 0 else f"FAILED (exit={proc.returncode})"
        print(f"  Worker {i} finished: {status}")
    return results


def _find_chunk_dir(output_dir: Path, chunk_id: str) -> Path | None:
    """Find the timestamped directory the runner created for a chunk.

    The runner creates {output_dir}/{timestamp}_{chunk_id}/.
    Returns the path, or None if not found.
    """
    # FIX 1/2: deterministic lookup by glob on known chunk_id suffix
    matches = sorted(glob(str(output_dir / f"*_{chunk_id}")))
    if len(matches) == 1:
        return Path(matches[0])
    if len(matches) > 1:
        # Multiple matches — take the latest (most recent timestamp)
        return Path(matches[-1])
    return None


def _read_events_prefix(events_path: Path, chunk_id: str) -> tuple[list[dict], list[dict]]:
    """Read events.jsonl with prefix-only parsing.

    FIX 3: stops at first parse error. Returns (valid_events, parse_errors).
    """
    events = []
    errors = []
    if not events_path.exists():
        return events, errors
    for line_num, line in enumerate(events_path.open(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if "chunk_id" not in event:
                event["chunk_id"] = chunk_id
            events.append(event)
        except (json.JSONDecodeError, ValueError) as e:
            errors.append({
                "chunk_id": chunk_id,
                "line_number": line_num,
                "error": str(e),
            })
            break  # FIX 3: stop at first error
    return events, errors


def _merge_events(
    parent_dir: Path,
    chunk_dirs: list[tuple[int, Path]],
    expected_pairs: set,
) -> dict:
    """Merge chunk event logs into merged_events.jsonl. Returns summary."""
    all_events = []
    all_errors = []
    skipped_events = 0

    # FIX 9: only process explicitly tracked chunk dirs
    for chunk_index, chunk_dir in chunk_dirs:
        chunk_id = f"chunk_{chunk_index}"
        events_path = chunk_dir / "events.jsonl"
        events, errors = _read_events_prefix(events_path, chunk_id)
        all_events.extend(events)
        all_errors.extend(errors)

    # FIX 8: validate required fields before sort
    valid_events = []
    for event in all_events:
        ts = event.get("timestamp")
        eid = event.get("event_id")
        etype = event.get("event_type")
        if not ts or eid is None or not etype:
            skipped_events += 1
            continue
        valid_events.append(event)

    # Sort deterministically
    valid_events.sort(key=lambda e: (
        e.get("timestamp", ""),
        e.get("chunk_id", ""),
        e.get("event_id", 0),
    ))

    # FIX 7: atomic write for merged output
    merged_path = parent_dir / "merged_events.jsonl"
    tmp_path = parent_dir / "merged_events.jsonl.tmp"
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        for event in valid_events:
            os.write(fd, (json.dumps(event, default=str) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp_path), str(merged_path))

    # Validate: find completed and missing pairs
    completed = set()
    terminal_counts = {}
    for event in valid_events:
        et = event.get("event_type", "")
        if et in ("case.end", "case.failed"):
            cid = event.get("case_id")
            cond = event.get("condition")
            if cid and cond:
                pair = (cid, cond)
                completed.add(pair)
                terminal_counts[pair] = terminal_counts.get(pair, 0) + 1

    missing = sorted(expected_pairs - completed)
    duplicates = sorted(p for p, c in terminal_counts.items() if c > 1)

    return {
        "total_events": len(valid_events),
        "total_expected": len(expected_pairs),
        "total_completed": len(completed),
        "missing_pairs": [list(p) for p in missing],
        "duplicate_pairs": [list(p) for p in duplicates],
        "parse_errors": all_errors,
        "skipped_events_missing_fields": skipped_events,
    }


def run_parallel(args, config, config_path: str):
    """Run ablation in parallel using N worker processes."""
    from runner import (
        load_cases, create_run_timestamp_dir,
        load_completed_pairs, preflight_verify_tests,
    )
    from condition_registry import validate_run
    from constants import VALID_CONDITIONS

    num_workers = config.execution.num_workers
    stagger = getattr(config.execution, "worker_stagger_seconds", 3)
    conditions = list(config.conditions.keys())
    for c in conditions:
        if c not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition {c!r}")

    # Load and filter cases
    cases = load_cases(case_id=args.case_id, cases_file=config.cases.source)
    max_cases = args.max_cases or getattr(config.cases, 'max_cases', 0)
    if max_cases and max_cases > 0:
        cases = cases[:max_cases]

    preflight_verify_tests(cases)
    validate_run(cases, conditions)

    # Create parent output directory
    parent_run_dir = Path(config.run.run_dir)
    parent_run_dir.mkdir(parents=True, exist_ok=True)

    # FIX 4: resume — pass all remaining cases, do not collapse to case_id
    skip = set()
    if args.resume:
        resume_dir = parent_run_dir / args.resume
        merged_path = resume_dir / "merged_events.jsonl"
        if merged_path.exists():
            skip = load_completed_pairs(merged_path)
            print(f"RESUME: {len(skip)} completed pairs from {merged_path}")
        # Remove fully-completed cases (all conditions done)
        remaining_pairs = {
            (case["id"], cond)
            for case in cases for cond in conditions
        } - skip
        if not remaining_pairs:
            print("All pairs already completed. Nothing to do.")
            return
        # Keep cases that have at least one remaining condition
        remaining_case_ids = {cid for cid, _ in remaining_pairs}
        cases = [c for c in cases if c["id"] in remaining_case_ids]
        output_dir = resume_dir
    else:
        output_dir = create_run_timestamp_dir(parent_run_dir, run_id=config.run.run_id)

    # FIX 5: compute expected_pairs AFTER filtering
    expected_pairs = {
        (case["id"], cond) for case in cases for cond in conditions
    }

    # Split cases into chunks
    n = min(num_workers, len(cases))
    chunks = _split_cases(cases, n)

    print(f"PARALLEL RUN: {len(cases)} cases x {len(conditions)} conditions = {len(cases) * len(conditions)} evals")
    print(f"  Workers: {n}, Stagger: {stagger}s")
    print(f"  Output: {output_dir}")

    tmp_dir = tempfile.mkdtemp(prefix="t3_parallel_")
    chunk_configs = []
    chunk_ids = []  # FIX 1: explicit tracking

    try:
        for i, chunk_cases in enumerate(chunks):
            chunk_cases_path = os.path.join(tmp_dir, f"cases_chunk_{i}.json")
            with open(chunk_cases_path, "w") as f:
                json.dump(chunk_cases, f)

            chunk_id = f"chunk_{i}"
            chunk_ids.append(chunk_id)

            chunk_config = _write_chunk_config(
                base_config_path=config_path,
                chunk_cases_path=os.path.abspath(chunk_cases_path),
                chunk_run_dir=str(output_dir),
                chunk_run_id=chunk_id,
                tmp_dir=tmp_dir,
                chunk_index=i,
            )
            chunk_configs.append(chunk_config)

        # Launch workers
        print(f"\nLaunching {n} workers...")
        t0 = time.monotonic()
        procs = _launch_workers(chunk_configs, stagger, output_dir)

        # Wait for completion
        worker_results = _wait_for_workers(procs)
        elapsed = time.monotonic() - t0
        print(f"\nAll workers finished in {elapsed:.1f}s")

        # Check for failures
        failed = [r for r in worker_results if r["exit_code"] != 0]
        if failed:
            print(f"\nWARNING: {len(failed)} worker(s) failed:")
            for r in failed:
                print(f"  chunk_{r['chunk_index']}: exit={r['exit_code']}")
                if r["stderr_tail"].strip():
                    print(f"    stderr: {r['stderr_tail'][-200:]}")

        # FIX 1/2: resolve chunk dirs from known chunk_ids, not directory scan
        resolved_chunk_dirs = []
        for i, chunk_id in enumerate(chunk_ids):
            chunk_dir = _find_chunk_dir(output_dir, chunk_id)
            if chunk_dir and (chunk_dir / "events.jsonl").exists():
                resolved_chunk_dirs.append((i, chunk_dir))
            else:
                print(f"  WARNING: chunk_{i} output directory not found or has no events")
        print(f"  Resolved {len(resolved_chunk_dirs)}/{n} chunk directories")

        # Merge events
        print("Merging event logs...")
        summary = _merge_events(output_dir, resolved_chunk_dirs, expected_pairs)

        summary["worker_results"] = worker_results
        summary["elapsed_seconds"] = round(elapsed, 1)
        summary["num_workers"] = n
        summary["num_chunks"] = len(chunks)
        summary["chunk_dirs"] = [str(d) for _, d in resolved_chunk_dirs]

        # Write merge summary (not critical path — direct write is fine)
        summary_path = output_dir / "merge_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        # Report
        print(f"\n  Events merged: {summary['total_events']}")
        print(f"  Completed: {summary['total_completed']}/{summary['total_expected']}")

        if summary.get("skipped_events_missing_fields", 0):
            print(f"  Skipped {summary['skipped_events_missing_fields']} events with missing fields")

        if summary["parse_errors"]:
            print(f"  Parse errors (stopped at first per chunk): {len(summary['parse_errors'])}")

        if summary["missing_pairs"]:
            print(f"  WARNING: {len(summary['missing_pairs'])} missing pairs")
            for p in summary["missing_pairs"][:10]:
                print(f"    {p[0]} / {p[1]}")
            if len(summary["missing_pairs"]) > 10:
                print(f"    ... and {len(summary['missing_pairs']) - 10} more")

        if summary["duplicate_pairs"]:
            print(f"\n  ERROR: {len(summary['duplicate_pairs'])} DUPLICATE terminal events!")
            for p in summary["duplicate_pairs"]:
                print(f"    {p[0]} / {p[1]}")
            raise RuntimeError(
                f"DUPLICATE TERMINAL EVENTS DETECTED: {len(summary['duplicate_pairs'])} pairs. "
                f"See {summary_path}"
            )

        # Build canonical merged_run.jsonl
        print("Building merged_run.jsonl...")
        from merge_run import build_merged_run
        try:
            merged_run_path = build_merged_run(
                output_dir,
                expected_case_ids={c["id"] for c in cases},
                expected_conditions=set(conditions),
                strict_completeness=not bool(summary["missing_pairs"]),
                strict_schema=False,
            )
        except ValueError as e:
            print(f"  WARNING: merged_run.jsonl build failed: {e}")
            merged_run_path = None

        print(f"\n  Merge summary: {summary_path}")
        print(f"  Merged events: {output_dir / 'merged_events.jsonl'}")
        if merged_run_path:
            print(f"  Merged run data: {merged_run_path}")
        print(f"  Output: {output_dir}")

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
