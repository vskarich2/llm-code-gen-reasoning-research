"""50-trial ablation: false_fix_deadlock × 5 conditions × gpt-5-mini.

50 trials launched in parallel, each with num_workers=1 (1 case × 5 conditions).
Total: 250 evals. Estimated: ~10 min.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_ffd_50trial.yaml"
N_TRIALS = 50
LOG_DIR = Path("logs/v2_ffd_50trial")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_ffd50_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    procs = []
    n_conds = len(base_cfg["conditions"])
    total = N_TRIALS * n_conds
    print(f"50-trial ablation: false_fix_deadlock × {n_conds} conditions × gpt-5-mini")
    print(f"  Total evals: {total}")
    print(f"  Parallelism: {N_TRIALS} concurrent processes")
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"v2_ffd_t{trial}"
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

    failed = sum(1 for _, proc, _, _ in procs if proc.returncode != 0)
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

    # Quick results
    conditions = sorted(set(r["condition"] for r in rows))
    print(f"\nRESULTS (false_fix_deadlock, gpt-5-mini, {N_TRIALS} trials):")
    print(f"{'='*70}")
    print(f"{'Condition':40s} {'Pass':>6s} {'Rate':>8s}")
    print(f"{'-'*70}")
    for cond in conditions:
        cr = [r for r in rows if r["condition"] == cond]
        p = sum(1 for r in cr if r["evaluation"].get("pass"))
        t = len(cr)
        rate = f"{100*p/t:.0f}%" if t else "-"
        print(f"{cond:40s} {p:>3d}/{t:<3d} {rate:>8s}")


if __name__ == "__main__":
    main()
