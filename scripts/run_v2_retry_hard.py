"""Run retry v2 on 3 hard cases: 5 trials, all in parallel."""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_retry_hard_cases.yaml"
N_TRIALS = 5
LOG_DIR = Path("logs/v2_retry_hard_critique")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_retry_hard_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    procs = []
    print(f"Retry V2 hard cases: 3 cases × 3 conditions × {N_TRIALS} trials")
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"v2_retry_hard_t{trial}"
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

    # Merge and report
    print("\nBuilding merged_run.jsonl...")
    from core.pipeline.orchestration import build_merged_run
    try:
        path = build_merged_run(str(LOG_DIR), strict_completeness=False, strict_schema=False)
        rows = [json.loads(l) for l in open(path)]
        print(f"  {len(rows)} rows")
    except Exception as e:
        print(f"  Merge failed: {e}")
        return

    # Analyze
    from collections import defaultdict
    conditions = sorted(set(r["condition"] for r in rows))

    print(f"\nRESULTS:")
    print(f"{'='*70}")
    for cid in ["async_race_lock", "false_fix_deadlock", "invariant_partial_fail"]:
        cr = [r for r in rows if r["case_id"] == cid]
        if not cr:
            print(f"  {cid}: no data")
            continue
        print(f"\n  {cid}:")
        for cond in conditions:
            ccr = [r for r in cr if r["condition"] == cond]
            if not ccr: continue
            p = sum(1 for r in ccr if r["evaluation"].get("pass"))
            t = len(ccr)
            cats = defaultdict(int)
            for r in ccr:
                cats[r["evaluation"].get("v2_category", "?")] += 1
            # Check retry attempts
            attempts = [r["evaluation"].get("num_attempts", 1) for r in ccr]
            retry_wins = [r["evaluation"].get("retry_passed_at") for r in ccr if r["evaluation"].get("retry_passed_at") is not None]
            cat_str = ", ".join(f"{c[:8]}={n}" for c, n in sorted(cats.items(), key=lambda x: -x[1]))
            avg_att = sum(attempts) / len(attempts) if attempts else 0
            print(f"    {cond:20s} {p}/{t} pass  avg_attempts={avg_att:.1f}  retry_wins={len(retry_wins)}  [{cat_str}]")


if __name__ == "__main__":
    main()
