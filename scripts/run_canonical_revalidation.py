"""Canonical revalidation: 6 recursion-contaminated cases × 10 trials.

6 cases × 3 conditions × 10 trials = 180 evals.
Each trial launches runner.py with --case-id filtering via per-case config_storage.
All 10 trials run concurrently (each with 1 worker since only 6 cases).
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_canonical_revalidation.yaml"
CASES = [
    "effect_order_b", "effect_order_c",
    "retry_dup_b", "retry_dup_c",
    "partial_rollback_b", "partial_rollback_c",
]
N_TRIALS = 10
LOG_DIR = Path("logs/v2_canonical_revalidation")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_reval_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    # Write a cases file with only the 6 target cases
    all_cases = json.load(open("cases_v2.json"))
    target_cases = [c for c in all_cases if c["id"] in CASES]
    assert len(target_cases) == len(CASES), (
        f"Missing cases: {set(CASES) - set(c['id'] for c in target_cases)}")

    cases_file = Path(tmp_dir) / "revalidation_cases.json"
    cases_file.write_text(json.dumps(target_cases, indent=2))

    total_evals = len(CASES) * 3 * N_TRIALS
    print(f"Canonical Revalidation")
    print(f"  Cases: {CASES}")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Total evaluations: {total_evals}")
    print(f"  Output: {LOG_DIR}")
    print()

    procs = []
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"reval_t{trial}"
        cfg["run"]["run_dir"] = str(LOG_DIR)
        cfg["execution"]["num_workers"] = 6
        cfg["cases"]["source"] = str(cases_file)

        trial_config = Path(tmp_dir) / f"reval_t{trial}.yaml"
        with open(trial_config, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        stdout_f = open(LOG_DIR / f"reval_t{trial}_stdout.log", "w")
        stderr_f = open(LOG_DIR / f"reval_t{trial}_stderr.log", "w")

        cmd = [sys.executable, "runner.py", "--config", str(trial_config)]
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((f"t{trial}", proc, stdout_f, stderr_f))
        print(f"  Launched trial {trial} (pid={proc.pid})")

    print(f"\n  {len(procs)} trials running concurrently...")
    print()

    # Wait for all
    failures = []
    for name, proc, so, se in procs:
        proc.wait()
        so.close()
        se.close()
        if proc.returncode != 0:
            failures.append(name)
            stderr_path = LOG_DIR / f"reval_{name}_stderr.log"
            print(f"  FAIL {name} (exit {proc.returncode})")
        else:
            print(f"  OK   {name}")

    elapsed = time.monotonic() - t0
    print(f"\n  All trials done in {elapsed:.1f}s")

    if failures:
        print(f"\n  FAILURES: {failures}")

    # Aggregate results
    print(f"\n{'=' * 60}")
    print(f"  REVALIDATION RESULTS")
    print(f"{'=' * 60}")

    from collections import Counter, defaultdict

    case_cond_results = defaultdict(list)
    total_recursion = 0

    for trial in range(1, N_TRIALS + 1):
        run_dirs = sorted(LOG_DIR.glob(f"*_reval_t{trial}"))
        for run_dir in run_dirs:
            ef = run_dir / "events.jsonl"
            if not ef.exists():
                continue
            for line in open(ef):
                ev = json.loads(line)
                if ev.get("event_type") != "case.end":
                    continue
                cid = ev.get("case_id")
                cond = ev.get("condition")
                payload = ev.get("payload", {})
                passed = payload.get("pass", False)
                reasons = payload.get("reasons", [])
                has_recursion = any(
                    "recursion" in str(r).lower() for r in reasons)
                if has_recursion:
                    total_recursion += 1
                case_cond_results[(cid, cond)].append(passed)

    print(f"\n  RecursionErrors: {total_recursion}")
    print()

    # Per-case summary
    print(f"  {'case':25s} {'baseline':>10s} {'leg_v2':>10s} {'lean':>10s}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
    for cid in CASES:
        parts = []
        for cond in ["baseline_v2", "leg_reduction_v2",
                      "leg_reduction_lean_v2"]:
            results = case_cond_results.get((cid, cond), [])
            if results:
                p = sum(results)
                parts.append(f"{p}/{len(results)}")
            else:
                parts.append("?")
        print(f"  {cid:25s} {parts[0]:>10s} {parts[1]:>10s} {parts[2]:>10s}")

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
