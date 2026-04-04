"""50-trial ablation: 5 LEG hotspot cases × 5 conditions × gpt-5-mini.

50 parallel trial processes. Total: 1,250 evals. ~12 min.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_leg_hotspots_50trial.yaml"
N_TRIALS = 50
LOG_DIR = Path("logs/v2_leg_hotspots_50trial")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_hotspot50_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    n_cases = 5
    n_conds = len(base_cfg["conditions"])
    total = n_cases * n_conds * N_TRIALS
    print(f"LEG hotspot ablation: {n_cases} cases × {n_conds} conditions × {N_TRIALS} trials = {total} evals")
    print(f"  50 parallel processes")

    procs = []
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"v2_hotspot_t{trial}"
        cfg["run"]["run_dir"] = str(LOG_DIR)

        trial_config = Path(tmp_dir) / f"t{trial}.yaml"
        with open(trial_config, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        stdout_f = open(LOG_DIR / f"t{trial}_stdout.log", "w")
        stderr_f = open(LOG_DIR / f"t{trial}_stderr.log", "w")

        cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((trial, proc, stdout_f, stderr_f))

        if trial % 10 == 0:
            print(f"  Launched {trial}/{N_TRIALS}")
        time.sleep(0.3)

    print(f"\n{N_TRIALS} trials launched. Waiting...")

    for trial, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()

    elapsed = time.monotonic() - t0
    failed = sum(1 for _, p, _, _ in procs if p.returncode != 0)
    print(f"\nAll trials finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")
    if failed:
        print(f"  WARNING: {failed} trials failed")

    # Merge
    print("\nBuilding merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        print(f"  {len(rows)}/{total} rows")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    # Results per case per condition
    cases = sorted(set(r["case_id"] for r in rows))
    conditions = sorted(set(r["condition"] for r in rows))

    print(f"\nRESULTS:")
    print(f"{'='*90}")
    for cid in cases:
        cr = [r for r in rows if r["case_id"] == cid]
        print(f"\n  {cid}:")
        for cond in conditions:
            ccr = [r for r in cr if r["condition"] == cond]
            if not ccr: continue
            p = sum(1 for r in ccr if r["evaluation"].get("pass"))
            t = len(ccr)
            cs = cond.replace("retry_leg_critique_", "crit_").replace("_v2", "")
            print(f"    {cs:30s} {p}/{t} ({100*p/t:.0f}%)")


if __name__ == "__main__":
    main()
