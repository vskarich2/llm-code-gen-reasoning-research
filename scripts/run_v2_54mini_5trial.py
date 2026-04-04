"""Launch gpt-5.4-mini ablation: 5 trials, all in parallel.

50 concurrent workers (10 per trial × 5 trials).
Estimated: ~8-10 minutes.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_full_54mini_5t.yaml"
N_TRIALS = 5
LOG_DIR = Path("logs/v2_full_ablation_54mini")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_54mini_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    procs = []
    print(f"Launching gpt-5.4-mini × {N_TRIALS} trials (10 workers each = 50 concurrent)")
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"v2_54mini_t{trial}"
        cfg["run"]["run_dir"] = str(LOG_DIR)

        trial_config = Path(tmp_dir) / f"54mini_t{trial}.yaml"
        with open(trial_config, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        stdout_f = open(LOG_DIR / f"t{trial}_stdout.log", "w")
        stderr_f = open(LOG_DIR / f"t{trial}_stderr.log", "w")

        cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((f"t{trial}", proc, stdout_f, stderr_f))
        print(f"  t{trial} launched (pid={proc.pid})")
        time.sleep(1)

    print(f"\n{len(procs)} trials launched. Waiting...")
    print(f"  Dashboard: .venv/bin/python scripts/live_dashboard_v2.py {LOG_DIR} --interval 15")
    print()

    for name, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()
        status = "OK" if proc.returncode == 0 else f"FAILED (exit={proc.returncode})"
        print(f"  {name}: {status}")

    elapsed = time.monotonic() - t0
    print(f"\nAll trials finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Final merge + dashboard
    print("\nBuilding merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        expected = 58 * 3 * 5
        print(f"  {len(rows)}/{expected} rows")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    print("Writing final dashboard...")
    from core.logging_.v2_metrics import compute_v2_metrics
    from core.logging_.v2_dashboard import write_v2_dashboard
    metrics = compute_v2_metrics(rows, expected_cases=58, expected_conditions=3, expected_trials=5)
    write_v2_dashboard(metrics, LOG_DIR / "dashboard_v2_final.txt")
    print(f"  Dashboard: {LOG_DIR / 'dashboard_v2_final.txt'}")


if __name__ == "__main__":
    main()
