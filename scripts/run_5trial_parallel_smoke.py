"""Run 5-trial parallel smoke test.

All trials launch in parallel. Each trial uses the parallel runner (2 workers).
Total concurrent processes: N_TRIALS x num_workers = 5 x 2 = 10 workers.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

BASE_CONFIG = "configs/v2_parallel_5trial_smoke.yaml"
N_TRIALS = 5


def main():
    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    tmp_dir = tempfile.mkdtemp(prefix="t3_5trial_")

    # Launch all trials in parallel
    procs = []
    log_dir = Path("logs/v2_parallel_5trial_smoke")
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"Launching {N_TRIALS} trials in parallel...")
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))  # deep copy
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"v2_par5t_t{trial}"

        trial_config = Path(tmp_dir) / f"trial_{trial}.yaml"
        with open(trial_config, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        stdout_f = open(log_dir / f"trial_{trial}_stdout.log", "w")
        stderr_f = open(log_dir / f"trial_{trial}_stderr.log", "w")

        cmd = [
            sys.executable, "runner.py",
            "--config", str(trial_config),
            "--max-cases", "3",
        ]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((trial, proc))
        print(f"  Trial {trial} launched (pid={proc.pid})")
        time.sleep(1)  # slight stagger to avoid config race

    # Wait for all
    print(f"\nWaiting for {N_TRIALS} trials to complete...")
    for trial, proc in procs:
        proc.wait()
        status = "OK" if proc.returncode == 0 else f"FAILED (exit={proc.returncode})"
        print(f"  Trial {trial}: {status}")

    elapsed = time.monotonic() - t0
    print(f"\nAll {N_TRIALS} trials finished in {elapsed:.1f}s")

    # Validate all trials
    print(f"\nValidating results...")
    import json
    for d in sorted(log_dir.iterdir()):
        if not d.is_dir():
            continue
        summary = d / "merge_summary.json"
        if summary.exists():
            s = json.loads(summary.read_text())
            c = s["total_completed"]
            e = s["total_expected"]
            m = len(s["missing_pairs"])
            dup = len(s["duplicate_pairs"])
            el = s.get("elapsed_seconds", "?")
            print(f"  {d.name}: {c}/{e} completed, missing={m}, dup={dup}, elapsed={el}s")
        else:
            print(f"  {d.name}: NO merge_summary (serial run or incomplete)")

    print(f"\nTotal wall-clock: {elapsed:.1f}s for {N_TRIALS} trials")


if __name__ == "__main__":
    main()
