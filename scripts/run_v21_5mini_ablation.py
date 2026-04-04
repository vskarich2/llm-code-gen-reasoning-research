"""V2.1 ablation: gpt-5-mini + gpt-5.4-mini, 3 conditions, 10 trials.

2 models: gpt-5-mini, gpt-5.4-mini
3 conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2
10 trials per model
58 cases each
Evaluator: gpt-5-mini

Total: 58 x 2 x 3 x 10 = 3,480 evals
Parallelism: 20 processes x 10 workers = 200 concurrent API calls
Estimated wall clock: ~7-8 minutes
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
LOG_DIR = Path("logs/v21_5mini_ablation")

CONDITIONS = {
    "baseline_v2": {"retry": {"enabled": False}},
    "leg_reduction_v2": {"retry": {"enabled": False}},
    "leg_reduction_lean_v2": {"retry": {"enabled": False}},
}

MODELS = {
    "5mini": {
        "name": "gpt-5-mini",
        "temperature": 0.0,
        "max_tokens": 128000,
        "top_p": 1.0,
    },
    "54mini": {
        "name": "gpt-5.4-mini",
        "temperature": 0.0,
        "max_tokens": 128000,
        "top_p": 1.0,
    },
}

EVALUATOR = {
    "name": "gpt-5-mini",
    "temperature": 0.0,
    "max_tokens": 128000,
}

BASE_CFG_TEMPLATE = {
    "experiment": {
        "tags": ["v2.1", "ablation", "5mini"],
        "seed": 42,
    },
    "cases": {"source": "cases_v2.json", "mode": "all", "max_cases": 0},
    "evaluation": {
        "execution_mode": "in_process",
        "subprocess_timeout": 30,
        "classifier_mode": "grounded",
        "leg": {"enabled": True},
        "failure_classification": {"enabled": True},
        "alignment": {"enabled": True},
    },
    "execution": {
        "worker_stagger_seconds": 2,
        "token_budgets": {
            "gpt-5-mini": 16000,
            "gpt-5.4-mini": 16000,
            "default": 16000,
        },
    },
    "prompts": {"output_format": "v2"},
    "logging": {
        "level": "INFO",
        "output_dir": "logs/",
        "store": {"raw_prompts": True, "raw_outputs": True},
        "redis": {"enabled": False},
    },
    "trials": 1,
}


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_5mini_abl_")

    total_runs = len(MODELS) * N_TRIALS
    total_evals = 58 * len(CONDITIONS) * total_runs
    print(f"V2.1 ABLATION: gpt-5-mini + gpt-5.4-mini")
    print(f"  Models: {[m['name'] for m in MODELS.values()]}")
    print(f"  Conditions: {list(CONDITIONS.keys())}")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Cases: 58 (all)")
    print(f"  Total evals: {total_evals}")
    print(f"  Parallel runs: {total_runs}")
    print(f"  Workers/run: {WORKERS_PER_RUN}")
    print(f"  Peak concurrent: {total_runs * WORKERS_PER_RUN}")
    print(f"  Output: {LOG_DIR}")
    print()

    t0 = time.monotonic()
    procs = []

    for model_key, model_cfg in MODELS.items():
        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(BASE_CFG_TEMPLATE))
            cfg["experiment"]["name"] = (
                f"v21_ablation_{model_key}")
            cfg["experiment"]["description"] = (
                f"V2.1 ablation: {model_cfg['name']} gen, "
                f"gpt-5-mini eval")
            cfg["run"] = {
                "trial": trial,
                "run_id": f"v21_{model_key}_t{trial}",
                "run_dir": str(LOG_DIR),
            }
            cfg["models"] = {
                "generation": [dict(model_cfg)],
                "evaluator": dict(EVALUATOR),
            }
            cfg["conditions"] = dict(CONDITIONS)
            cfg["execution"]["num_workers"] = WORKERS_PER_RUN

            trial_config = (
                Path(tmp_dir) / f"{model_key}_t{trial}.yaml")
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            stdout_f = open(
                LOG_DIR / f"{model_key}_t{trial}_stdout.log", "w")
            stderr_f = open(
                LOG_DIR / f"{model_key}_t{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py",
                   "--config", str(trial_config)]
            proc = subprocess.Popen(
                cmd, stdout=stdout_f, stderr=stderr_f)
            procs.append((
                f"{model_key}_t{trial}", proc, stdout_f, stderr_f))
            print(f"  Launched {model_key}_t{trial} "
                  f"(pid={proc.pid})")
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
    print(f"\nAll runs finished in {elapsed:.1f}s "
          f"({elapsed / 60:.1f}m)")

    if failed:
        print(f"\nWARNING: {len(failed)} failed: {failed}")


if __name__ == "__main__":
    main()
