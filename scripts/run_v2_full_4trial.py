"""Launch full v2 ablation: 3 models × 4 trials, all in parallel.

72 concurrent workers (6 per run × 12 runs).
Estimated: ~15-20 minutes.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIGS = {
    "nano": "config_storage/v2_full_nano_1t.yaml",
    "4omini": "config_storage/v2_full_4omini_1t.yaml",
    "5mini": "config_storage/v2_full_5mini_1t.yaml",
}
N_TRIALS = 4
WORKERS_PER_RUN = 6
LOG_DIR = Path("logs/v2_full_ablation_4t")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_4trial_")

    procs = []
    print(f"Launching {len(BASE_CONFIGS)} models × {N_TRIALS} trials = {len(BASE_CONFIGS) * N_TRIALS} runs")
    print(f"  Workers per run: {WORKERS_PER_RUN}")
    print(f"  Total concurrent workers: {len(BASE_CONFIGS) * N_TRIALS * WORKERS_PER_RUN}")
    print(f"  Output: {LOG_DIR}")
    print()

    t0 = time.monotonic()

    for model_name, base_cfg_path in BASE_CONFIGS.items():
        with open(base_cfg_path) as f:
            base_cfg = yaml.safe_load(f)

        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            cfg["run"]["trial"] = trial
            cfg["run"]["run_id"] = f"v2_{model_name}_t{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["execution"]["num_workers"] = WORKERS_PER_RUN

            trial_config = Path(tmp_dir) / f"{model_name}_t{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            stdout_f = open(LOG_DIR / f"{model_name}_t{trial}_stdout.log", "w")
            stderr_f = open(LOG_DIR / f"{model_name}_t{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
            proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
            procs.append((f"{model_name}_t{trial}", proc, stdout_f, stderr_f))
            print(f"  {model_name}_t{trial} launched (pid={proc.pid})")
            time.sleep(1)

    print(f"\n{len(procs)} runs launched. Waiting...")
    print(f"  Dashboard: .venv/bin/python scripts/live_dashboard_v2.py {LOG_DIR} --interval 15")
    print()

    for name, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()
        status = "OK" if proc.returncode == 0 else f"FAILED (exit={proc.returncode})"
        print(f"  {name}: {status}")

    elapsed = time.monotonic() - t0
    print(f"\nAll runs finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Final merge
    print("\nBuilding merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        models = set(r.get("model") for r in rows)
        trials = set(r.get("trial") for r in rows)
        expected = 58 * 3 * len(models) * len(trials)
        print(f"  {len(rows)}/{expected} rows, {len(models)} models, {len(trials)} trials")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    # Final dashboard
    print("Writing final dashboard...")
    from core.logging_.v2_metrics import compute_v2_metrics
    from core.logging_.v2_dashboard import write_v2_dashboard
    metrics = compute_v2_metrics(rows, expected_cases=58, expected_conditions=3, expected_trials=N_TRIALS)
    write_v2_dashboard(metrics, LOG_DIR / "dashboard_v2_final.txt")
    print(f"  Dashboard: {LOG_DIR / 'dashboard_v2_final.txt'}")


if __name__ == "__main__":
    main()
