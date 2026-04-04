"""Smoke test: canonical execution on effect_order_b, 5 trials.

1 case × 3 conditions × 5 trials = 15 evaluations.
Uses gpt-5-mini for both generation and evaluation.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_canonical_smoke.yaml"
CASE_ID = "effect_order_b"
N_TRIALS = 5
LOG_DIR = Path("logs/v2_canonical_smoke")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_smoke_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    total_evals = 1 * 3 * N_TRIALS  # 1 case × 3 conditions × 5 trials
    print(f"Canonical Smoke Test: {CASE_ID}")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2")
    print(f"  Execution mode: canonical")
    print(f"  Total evaluations: {total_evals}")
    print(f"  Output: {LOG_DIR}")
    print()

    procs = []
    t0 = time.monotonic()

    for trial in range(1, N_TRIALS + 1):
        cfg = yaml.safe_load(yaml.dump(base_cfg))
        cfg["run"]["trial"] = trial
        cfg["run"]["run_id"] = f"canonical_smoke_t{trial}"
        cfg["run"]["run_dir"] = str(LOG_DIR)

        trial_config = Path(tmp_dir) / f"smoke_t{trial}.yaml"
        with open(trial_config, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        stdout_f = open(LOG_DIR / f"smoke_t{trial}_stdout.log", "w")
        stderr_f = open(LOG_DIR / f"smoke_t{trial}_stderr.log", "w")

        cmd = [
            sys.executable, "runner.py",
            "--config", str(trial_config),
            "--case-id", CASE_ID,
        ]
        print(f"  Launching trial {trial}: {' '.join(cmd[-4:])}")
        proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
        procs.append((f"t{trial}", proc, stdout_f, stderr_f))

    # Wait for all
    print(f"\n  Waiting for {len(procs)} trials...")
    failures = []
    for name, proc, so, se in procs:
        proc.wait()
        so.close()
        se.close()
        if proc.returncode != 0:
            failures.append(name)
            stderr_path = LOG_DIR / f"smoke_{name}_stderr.log"
            print(f"  FAIL {name} (exit {proc.returncode})")
            if stderr_path.exists():
                err = stderr_path.read_text()[-500:]
                print(f"    stderr tail: {err}")
        else:
            print(f"  OK   {name}")

    elapsed = time.monotonic() - t0
    print(f"\n  Done in {elapsed:.1f}s")

    if failures:
        print(f"\n  FAILURES: {failures}")
        sys.exit(1)

    # Quick summary from events
    print(f"\n  Checking results...")
    import json
    from collections import Counter

    events_dir = LOG_DIR
    pass_count = 0
    fail_count = 0
    categories = Counter()
    recursion_errors = 0

    for events_file in sorted(events_dir.glob("**/events.jsonl")):
        for line in open(events_file):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "case.end":
                continue
            raw_ev = ev.get("raw_ev") or ev.get("payload", {}).get("raw_ev", {})
            if not raw_ev:
                continue
            passed = raw_ev.get("pass", False)
            cat = raw_ev.get("execution_category", "unknown")
            if passed:
                pass_count += 1
            else:
                fail_count += 1
            categories[cat] += 1
            # Check for recursion
            reasons = raw_ev.get("reasons", [])
            if any("recursion" in str(r).lower() for r in reasons):
                recursion_errors += 1
            subtype = raw_ev.get("execution_subtype", "")
            if subtype and "Recursion" in str(subtype):
                recursion_errors += 1

    total = pass_count + fail_count
    print(f"\n{'=' * 50}")
    print(f"  SMOKE TEST RESULTS ({CASE_ID})")
    print(f"  Total evaluations: {total} / {total_evals} expected")
    print(f"  Pass:  {pass_count}")
    print(f"  Fail:  {fail_count}")
    print(f"  Categories: {dict(categories)}")
    print(f"  RecursionErrors: {recursion_errors}")
    print(f"{'=' * 50}")

    if recursion_errors > 0:
        print("\n  CRITICAL: RecursionError detected on canonical path!")
        sys.exit(1)
    if total == 0:
        print("\n  WARNING: No results found. Check logs.")
        sys.exit(1)

    print("\n  Smoke test PASSED.")


if __name__ == "__main__":
    main()
