"""feature_flag_drift retry: 4 models × 5 conditions × 10 trials, all parallel."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

MODELS = {
    "nano": "config_storage/v2_full_nano_1t.yaml",
    "4omini": "config_storage/v2_full_4omini_1t.yaml",
    "5mini": "config_storage/v2_full_5mini_1t.yaml",
    "54mini": "config_storage/v2_full_54mini_5t.yaml",
}
N_TRIALS = 10
LOG_DIR = Path("logs/v2_ffd2_retry")
CONDITIONS = [
    "baseline_v2",
    "retry_bare_retry_v2",
    "retry_leg_critique_strict_v2",
    "retry_leg_critique_moderate_v2",
    "retry_no_contract_v2",
]


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_ffd2_")

    total_runs = len(MODELS) * N_TRIALS
    total_evals = len(MODELS) * len(CONDITIONS) * N_TRIALS
    print(f"feature_flag_drift: {len(MODELS)} models × {len(CONDITIONS)} conditions × {N_TRIALS} trials = {total_evals} evals")
    print(f"  {total_runs} parallel processes")

    procs = []
    t0 = time.monotonic()

    for model_key, base_config in MODELS.items():
        with open(base_config) as f:
            base_cfg = yaml.safe_load(f)

        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            cfg["run"]["trial"] = trial
            cfg["run"]["run_id"] = f"v2_ffd2_{model_key}_t{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["execution"]["num_workers"] = 1
            cfg["cases"]["source"] = "cases_v2_ffd2.json"
            cfg["cases"]["max_cases"] = 0
            cfg["conditions"] = {c: {"retry": {"enabled": False}} for c in CONDITIONS}

            trial_config = Path(tmp_dir) / f"{model_key}_t{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            stdout_f = open(LOG_DIR / f"{model_key}_t{trial}_stdout.log", "w")
            stderr_f = open(LOG_DIR / f"{model_key}_t{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
            proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
            procs.append((f"{model_key}_t{trial}", proc, stdout_f, stderr_f))
            time.sleep(0.3)

    print(f"\n{len(procs)} processes launched. Waiting...")

    for name, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()

    elapsed = time.monotonic() - t0
    failed = sum(1 for _, p, _, _ in procs if p.returncode != 0)
    print(f"\nAll finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")
    if failed:
        print(f"  WARNING: {failed} failed")

    # Merge + results
    print("\nMerging...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        print(f"  {len(rows)}/{total_evals} rows")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    models = sorted(set(r["model"] for r in rows))
    conditions = sorted(set(r["condition"] for r in rows))

    print(f"\nRESULTS (feature_flag_drift):")
    print(f"{'='*90}")
    for m in models:
        mr = [r for r in rows if r["model"] == m]
        print(f"\n  {m}:")
        for c in conditions:
            cr = [r for r in mr if r["condition"] == c]
            if not cr: continue
            p = sum(1 for r in cr if r["evaluation"].get("pass"))
            t = len(cr)
            cs = c.replace("retry_leg_critique_", "crit_").replace("_v2", "")
            print(f"    {cs:30s} {p}/{t} ({100*p/t:.0f}%)")


if __name__ == "__main__":
    main()
