#!/usr/bin/env python
"""Full ablation launcher: 3 models x 5 trials x 58 cases x 2 conditions.

Runs up to 6 concurrent runner.py processes.
Resume-safe: re-run to pick up where it left off.

Usage:
    .venv/bin/python scripts/run_full_ablation.py
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PYTHON = str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python")
MAX_PARALLEL = 15  # 5 trials x 3 models — all run simultaneously
CONFIGS_DIR = Path("configs/ablation_full")
LOG_DIR = Path("logs/ablation_full")
EXPECTED_EVENTS_PER_TRIAL = 58 * 2  # 58 cases x 2 conditions = 116

_stop = False


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def find_resume_dir(cfg_path):
    """Find existing timestamp dir for this config's run_id. Returns (ts_dir, n_events) or (None, 0)."""
    import yaml
    with open(cfg_path) as f:
        c = yaml.safe_load(f)
    run_dir = Path(c["run"]["run_dir"])
    run_id = c["run"]["run_id"]

    if not run_dir.exists():
        return None, 0

    for ts_dir in sorted(run_dir.iterdir(), reverse=True):
        if not ts_dir.is_dir():
            continue
        meta_path = ts_dir / "metadata.json"
        events_path = ts_dir / "events.jsonl"
        if not meta_path.exists() or not events_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("run_id") != run_id:
            continue
        n_events = sum(1 for line in events_path.open() if line.strip())
        return ts_dir.name, n_events

    return None, 0


def main():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    configs = sorted(CONFIGS_DIR.glob("*.yaml"))
    print(f"=== FULL ABLATION ===")
    print(f"  Configs: {len(configs)}")
    print(f"  Parallelism: {MAX_PARALLEL}")
    print(f"  Expected per trial: {EXPECTED_EVENTS_PER_TRIAL} events")
    print()

    # Classify each config: SKIP (complete), RESUME (partial), or FRESH
    jobs = []
    skip_count = 0
    for cfg in configs:
        name = cfg.stem
        ts_dir, n_events = find_resume_dir(cfg)

        if ts_dir and n_events >= EXPECTED_EVENTS_PER_TRIAL:
            print(f"  COMPLETE: {name} ({n_events} events) — skipping")
            skip_count += 1
            continue
        elif ts_dir and n_events > 0:
            print(f"  RESUME:   {name} -> {ts_dir} ({n_events}/{EXPECTED_EVENTS_PER_TRIAL} events)")
            jobs.append((cfg, name, ["--resume", ts_dir]))
        else:
            jobs.append((cfg, name, []))

    print(f"\n  {skip_count} complete, {len(jobs)} to run")
    print()

    if not jobs:
        print("All runs complete. Nothing to do.")
        return

    # Launch with max parallelism
    active = {}  # pid -> (name, process, log_file)
    results = {"done": 0, "failed": 0}

    def reap_finished():
        finished = []
        for pid, (name, proc, log_file) in active.items():
            ret = proc.poll()
            if ret is not None:
                finished.append(pid)
                if ret == 0:
                    print(f"  DONE:   {name}")
                    results["done"] += 1
                else:
                    print(f"  FAILED: {name} (exit={ret}) — see {log_file}")
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

            with open(log_file, "a") as lf:
                lf.write(f"\n--- Launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                lf.write(f"CMD: {' '.join(cmd)}\n")

            log_fh = open(log_file, "a")
            proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT)
            active[proc.pid] = (name, proc, log_file)
            print(f"  [LAUNCH] {name} (PID {proc.pid}) {extra_args if extra_args else ''}")

        # Wait a bit, then reap
        time.sleep(2)
        reap_finished()

    print(f"\n=== COMPLETE ===")
    print(f"  Done: {results['done']}, Failed: {results['failed']}, Skipped: {skip_count}")
    if results["failed"] > 0:
        print(f"  Re-run this script to resume failed runs.")


if __name__ == "__main__":
    main()
