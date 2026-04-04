"""V2.1 validation ablation: 2 models x 2 conditions x 10 trials, all cases.

2 models: gpt-4.1-nano, gpt-4o-mini
2 conditions: baseline_v2, leg_reduction_v2
10 trials per model
51 cases each

Total: 51 x 2 x 2 x 10 = 2,040 evals
Parallelism: 20 processes x 6 workers = 120 concurrent API calls
Estimated wall clock: ~8-10 minutes
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

N_TRIALS = 10
WORKERS_PER_RUN = 6
STAGGER_SECONDS = 1
LOG_DIR = Path("logs/v21_validation")

BASE_CONFIGS = {
    "nano": "config_storage/v2_full_nano_1t.yaml",
    "4omini": "config_storage/v2_full_4omini_1t.yaml",
}

# Only these 2 conditions for V2.1 validation
V21_CONDITIONS = {
    "baseline_v2": {"retry": {"enabled": False}},
    "leg_reduction_v2": {"retry": {"enabled": False}},
}


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_v21_val_")

    total_runs = len(BASE_CONFIGS) * N_TRIALS
    total_evals = 51 * len(V21_CONDITIONS) * total_runs
    print(f"V2.1 VALIDATION ABLATION")
    print(f"  Models: {list(BASE_CONFIGS.keys())}")
    print(f"  Conditions: {list(V21_CONDITIONS.keys())}")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Cases: 51 (all)")
    print(f"  Total evals: {total_evals}")
    print(f"  Parallel runs: {total_runs}")
    print(f"  Workers/run: {WORKERS_PER_RUN}")
    print(f"  Peak concurrent: {total_runs * WORKERS_PER_RUN}")
    print(f"  Output: {LOG_DIR}")
    print()

    t0 = time.monotonic()
    procs = []

    for model_name, base_cfg_path in BASE_CONFIGS.items():
        with open(base_cfg_path) as f:
            base_cfg = yaml.safe_load(f)

        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            cfg["run"]["trial"] = trial
            cfg["run"]["run_id"] = f"v21_{model_name}_t{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["execution"]["num_workers"] = WORKERS_PER_RUN
            cfg["conditions"] = dict(V21_CONDITIONS)
            cfg["experiment"]["name"] = f"v21_validation_{model_name}"

            trial_config = Path(tmp_dir) / f"{model_name}_t{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            stdout_f = open(
                LOG_DIR / f"{model_name}_t{trial}_stdout.log", "w")
            stderr_f = open(
                LOG_DIR / f"{model_name}_t{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py",
                   "--config", str(trial_config)]
            proc = subprocess.Popen(
                cmd, stdout=stdout_f, stderr=stderr_f)
            procs.append((
                f"{model_name}_t{trial}", proc, stdout_f, stderr_f))
            print(f"  Launched {model_name}_t{trial} (pid={proc.pid})")
            time.sleep(STAGGER_SECONDS)

    print(f"\n{len(procs)} runs launched. Waiting...\n")

    failed = []
    for name, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()
        if proc.returncode != 0:
            failed.append(name)
            print(f"  {name}: FAILED (exit={proc.returncode})")
        else:
            print(f"  {name}: OK")

    elapsed = time.monotonic() - t0
    print(f"\nAll runs finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")

    if failed:
        print(f"\nWARNING: {len(failed)} runs failed: {failed}")
        print("Check stderr logs:")
        for name in failed:
            print(f"  {LOG_DIR}/{name}_stderr.log")

    # Merge results
    print("\nMerging results...")
    try:
        from core.pipeline.orchestration import build_merged_run
        path = build_merged_run(
            str(LOG_DIR),
            strict_completeness=False,
            strict_schema=False)
        rows = [json.loads(line) for line in open(path)]
        models = sorted(set(r.get("model", "?") for r in rows))
        trials = sorted(set(r.get("trial", 0) for r in rows))
        print(f"  {len(rows)} total rows")
        print(f"  Models: {models}")
        print(f"  Trials: {trials}")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    # Dashboard
    print("\nWriting dashboard...")
    try:
        from core.logging_.v2_metrics import compute_v2_metrics
        from core.logging_.v2_dashboard import write_v2_dashboard
        metrics = compute_v2_metrics(
            rows, expected_cases=51,
            expected_conditions=2,
            expected_trials=N_TRIALS)
        dash_path = LOG_DIR / "dashboard_v21_validation.txt"
        write_v2_dashboard(metrics, dash_path)
        print(f"  Dashboard: {dash_path}")
    except Exception as e:
        print(f"  Dashboard failed: {e}")


if __name__ == "__main__":
    main()
