#!/usr/bin/env python
"""Focused 50-trial ablation: 2 models x 2 cases x 3 conditions x 50 trials.

Launches up to MAX_PARALLEL concurrent runner.py processes.
Each process does 6 evals (2 cases x 3 conditions) — finishes in ~60s.

Usage:
    .venv/bin/python scripts/run_focused_50t.py
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PYTHON = str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python")
MAX_PARALLEL = 25
CONFIGS_DIR = Path("config_storage/focused_50t")
LOG_DIR = Path("logs/focused_50t")
EXPECTED_EVENTS_PER_TRIAL = 2 * 3  # 2 cases x 3 conditions

_stop = False


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def main():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    configs = sorted(CONFIGS_DIR.glob("*.yaml"))
    print(f"=== FOCUSED 50-TRIAL ABLATION ===")
    print(f"  Configs: {len(configs)}")
    print(f"  Parallelism: {MAX_PARALLEL}")
    print(f"  Expected per trial: {EXPECTED_EVENTS_PER_TRIAL} evals")
    print(f"  Total evals: {len(configs) * EXPECTED_EVENTS_PER_TRIAL}")
    print()

    jobs = []
    for cfg in configs:
        jobs.append((cfg, cfg.stem, []))

    print(f"  {len(jobs)} jobs to run\n")

    if not jobs:
        print("Nothing to do.")
        return

    active = {}  # pid -> (name, process, log_fh)
    results = {"done": 0, "failed": 0}
    t0 = time.monotonic()

    def reap_finished():
        finished = []
        for pid, (name, proc, log_fh) in active.items():
            ret = proc.poll()
            if ret is not None:
                finished.append(pid)
                log_fh.close()
                if ret == 0:
                    results["done"] += 1
                else:
                    print(f"  FAILED: {name} (exit={ret})")
                    results["failed"] += 1
        for pid in finished:
            del active[pid]

    job_idx = 0
    while job_idx < len(jobs) or active:
        if _stop:
            print("\nStopping — sending SIGTERM to active processes...")
            for pid, (name, proc, _) in active.items():
                proc.terminate()
            for pid, (name, proc, _) in active.items():
                proc.wait(timeout=30)
            break

        # Launch new jobs up to MAX_PARALLEL
        while job_idx < len(jobs) and len(active) < MAX_PARALLEL:
            cfg, name, extra_args = jobs[job_idx]
            job_idx += 1

            log_file = LOG_DIR / f"{name}.log"
            cmd = [PYTHON, "runner.py", "--config", str(cfg)] + extra_args

            log_fh = open(log_file, "w")
            proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT)
            active[proc.pid] = (name, proc, log_fh)

        # Progress update every 5 seconds
        reap_finished()
        elapsed = time.monotonic() - t0
        done = results["done"] + results["failed"]
        if done > 0 and done % 10 == 0:
            rate = done / elapsed * 60
            remaining = len(jobs) - done - len(active)
            eta = remaining / (done / elapsed) if done > 0 else 0
            print(f"  [{done}/{len(jobs)}] {elapsed:.0f}s elapsed, {len(active)} active, ~{eta:.0f}s remaining")

        time.sleep(1)

    # Final reap
    for pid, (name, proc, log_fh) in list(active.items()):
        proc.wait()
        log_fh.close()
        if proc.returncode == 0:
            results["done"] += 1
        else:
            results["failed"] += 1

    elapsed = time.monotonic() - t0
    print(f"\n=== COMPLETE ===")
    print(f"  Done: {results['done']}, Failed: {results['failed']}")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")
    print(f"  Output: {LOG_DIR}")

    if results["failed"] > 0:
        print(f"\n  Check logs in {LOG_DIR}/ for failures.")

    # Merge all results into a single merged_run.jsonl
    print("\nMerging results...")
    merge_results(LOG_DIR)


def merge_results(log_dir: Path):
    """Find all events.jsonl across trial subdirs, merge into single file."""
    from glob import glob

    all_records = []
    event_files = sorted(glob(str(log_dir / "**/events.jsonl"), recursive=True))
    for ef in event_files:
        ef_path = Path(ef)
        # Extract chunk source info
        chunk_source = ef_path.parent.name
        for line in open(ef):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event["_chunk_source"] = chunk_source
                all_records.append(event)
            except json.JSONDecodeError:
                continue

    # Also collect run.jsonl records
    run_records = []
    run_files = sorted(glob(str(log_dir / "**/run.jsonl"), recursive=True))
    for rf in run_files:
        rf_path = Path(rf)
        chunk_source = rf_path.parent.name
        for line in open(rf):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                record["_chunk_source"] = chunk_source
                run_records.append(record)
            except json.JSONDecodeError:
                continue

    # Write merged files
    merged_events = log_dir / "merged_events.jsonl"
    with open(merged_events, "w") as f:
        for r in sorted(all_records, key=lambda e: (e.get("timestamp", ""), e.get("event_id", 0))):
            f.write(json.dumps(r, default=str) + "\n")

    merged_run = log_dir / "merged_run.jsonl"
    with open(merged_run, "w") as f:
        for r in run_records:
            f.write(json.dumps(r, default=str) + "\n")

    # Quick stats
    case_end = [r for r in all_records if r.get("event_type") == "case.end"]
    print(f"  Events: {len(all_records)}")
    print(f"  Run records: {len(run_records)}")
    print(f"  case.end events: {len(case_end)}")

    # Pass rates
    from collections import defaultdict
    stats = defaultdict(lambda: {"total": 0, "pass": 0})
    for e in case_end:
        key = (e.get("model", "?"), e.get("condition", "?"))
        ex = e.get("execution", {}) or {}
        stats[key]["total"] += 1
        if ex.get("passed"):
            stats[key]["pass"] += 1

    print(f"\n  Quick pass rates:")
    for (m, c), s in sorted(stats.items()):
        pr = s["pass"] / s["total"] * 100 if s["total"] else 0
        print(f"    {m:20s} x {c:25s}: {s['pass']:3d}/{s['total']:3d} = {pr:5.1f}%")


if __name__ == "__main__":
    main()
