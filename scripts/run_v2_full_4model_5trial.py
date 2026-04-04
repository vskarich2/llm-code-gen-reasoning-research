"""Launch full v2 ablation: 4 models × 5 trials, all in parallel.

80 concurrent workers (4 per run × 20 runs).
3,480 evaluations. Estimated: ~20 minutes.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

MODELS = {
    "nano": {
        "name": "gpt-4.1-nano",
        "base_config": "config_storage/v2_full_nano_1t.yaml",
    },
    "4omini": {
        "name": "gpt-4o-mini",
        "base_config": "config_storage/v2_full_4omini_1t.yaml",
    },
    "5mini": {
        "name": "gpt-5-mini",
        "base_config": "config_storage/v2_full_5mini_1t.yaml",
    },
    "54mini": {
        "name": "gpt-5.4-mini",
        "base_config": "config_storage/v2_full_54mini_5t.yaml",
    },
}
N_TRIALS = 5
WORKERS_PER_RUN = 4
LOG_DIR = Path("logs/v2_full_4model_5trial")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_4m5t_")

    total_runs = len(MODELS) * N_TRIALS
    total_workers = total_runs * WORKERS_PER_RUN
    total_evals = len(MODELS) * 58 * 3 * N_TRIALS

    print(f"V2 Full Ablation: {len(MODELS)} models × {N_TRIALS} trials = {total_runs} runs")
    print(f"  Workers per run: {WORKERS_PER_RUN}")
    print(f"  Total concurrent workers: {total_workers}")
    print(f"  Total evaluations: {total_evals}")
    print(f"  Output: {LOG_DIR}")
    print()

    procs = []
    t0 = time.monotonic()

    for model_key, model_info in MODELS.items():
        with open(model_info["base_config"]) as f:
            base_cfg = yaml.safe_load(f)

        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            cfg["run"]["trial"] = trial
            cfg["run"]["run_id"] = f"v2_{model_key}_t{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["execution"]["num_workers"] = WORKERS_PER_RUN
            cfg["execution"]["worker_stagger_seconds"] = 2

            trial_config = Path(tmp_dir) / f"{model_key}_t{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            stdout_f = open(LOG_DIR / f"{model_key}_t{trial}_stdout.log", "w")
            stderr_f = open(LOG_DIR / f"{model_key}_t{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
            proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
            procs.append((f"{model_key}_t{trial}", proc, stdout_f, stderr_f))
            print(f"  {model_key}_t{trial} launched (pid={proc.pid})")
            time.sleep(0.5)

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

    # Final merge + dashboard
    print("\nBuilding merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        models = sorted(set(r.get("model") for r in rows))
        trials = sorted(set(r.get("trial") for r in rows))
        print(f"  {len(rows)}/{total_evals} rows, {len(models)} models, {len(trials)} trials")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    print("Writing final dashboard...")
    from core.logging_.v2_metrics import compute_v2_metrics
    from core.logging_.v2_dashboard import write_v2_dashboard
    metrics = compute_v2_metrics(rows, expected_cases=58, expected_conditions=3, expected_trials=5)
    write_v2_dashboard(metrics, LOG_DIR / "dashboard_v2_final.txt")
    print(f"  Dashboard: {LOG_DIR / 'dashboard_v2_final.txt'}")
    print(f"\nDone. Total wall-clock: {elapsed/60:.1f}m")


if __name__ == "__main__":
    main()
