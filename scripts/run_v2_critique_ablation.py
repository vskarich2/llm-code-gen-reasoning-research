"""Critique specificity ablation: 3 hard cases × 6 conditions × 5 trials."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_retry_critique_ablation.yaml"
N_TRIALS = 5
LOG_DIR = Path("logs/v2_retry_critique_ablation")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_crit_abl_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    procs = []
    n_conds = len(base_cfg["conditions"])
    print(f"Critique ablation: 3 cases × {n_conds} conditions × {N_TRIALS} trials")
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"v2_crit_abl_t{trial}"
        cfg["run"]["run_dir"] = str(LOG_DIR)

        trial_config = Path(tmp_dir) / f"t{trial}.yaml"
        with open(trial_config, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        stdout_f = open(LOG_DIR / f"t{trial}_stdout.log", "w")
        stderr_f = open(LOG_DIR / f"t{trial}_stderr.log", "w")

        cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((f"t{trial}", proc, stdout_f, stderr_f))
        print(f"  t{trial} launched (pid={proc.pid})")
        time.sleep(1)

    print(f"\nWaiting for {N_TRIALS} trials...")

    for name, proc, sf, ef in procs:
        proc.wait()
        sf.close()
        ef.close()
        status = "OK" if proc.returncode == 0 else f"FAILED (exit={proc.returncode})"
        print(f"  {name}: {status}")

    elapsed = time.monotonic() - t0
    print(f"\nAll trials finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Merge and analyze
    print("\nBuilding merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        print(f"  {len(rows)} rows")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    # Results
    conditions = sorted(set(r["condition"] for r in rows))
    hard_cases = ["async_race_lock", "false_fix_deadlock", "invariant_partial_fail"]

    print(f"\nRESULTS:")
    print(f"{'='*90}")
    for cid in hard_cases:
        cr = [r for r in rows if r["case_id"] == cid]
        if not cr:
            print(f"\n  {cid}: no data")
            continue
        print(f"\n  {cid}:")
        for cond in conditions:
            ccr = [r for r in cr if r["condition"] == cond]
            if not ccr: continue
            p = sum(1 for r in ccr if r["evaluation"].get("pass"))
            t = len(ccr)
            # Check critique info from trajectory
            critiques = []
            for r in ccr:
                traj = r["evaluation"].get("trajectory", [])
                for step in traj:
                    mc = step.get("mismatch_critique")
                    if mc:
                        critiques.append(mc)
            crit_str = f"  critiques={len(critiques)}" if critiques else ""
            print(f"    {cond:35s} {p}/{t} pass{crit_str}")
            if critiques:
                print(f"      example: {critiques[0]}")


if __name__ == "__main__":
    main()
