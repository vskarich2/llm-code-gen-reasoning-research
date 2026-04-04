"""Verification of 50-trial results table.

Reproduces all 22 case x model combinations from the published table,
50 trials each, 3 conditions (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2).

Throttled: MAX_PARALLEL=8, num_workers=4 per process.
Total: 22 combos x 3 conditions x 50 trials = 3,300 evals.
Estimated wall-clock: ~1-1.5 hours.
"""

import os
os.environ["PYTHONUNBUFFERED"] = "1"

import json
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_canonical_revalidation.yaml"
LOG_DIR = Path("logs/v2_verify_50trial")
N_TRIALS = 50
MAX_PARALLEL = 25
WORKERS_PER_PROCESS = 5

# Case x model combos from the results table (row 21 skipped: invalid)
# Row 24 is a subset of row 8, so also skipped.
MODEL_CASES = {
    "gpt-4.1-nano": [
        "cache_invalidation_order",
        "mutable_default_b",
        "lost_update",
        "check_then_act",
        "alias_config_c",
        "hidden_dep_multihop",
    ],
    "gpt-4o-mini": [
        "lost_update",
        "hidden_dep_multihop",
        "alias_config_c",
        "stale_cache_a",
    ],
    "gpt-5-mini": [
        "partial_rollback_c",
        "partial_rollback_b",
        "effect_order_c",
        "l3_state_pipeline",
        "invariant_partial_fail",
        "false_fix_deadlock",
        "hidden_dep_multihop",
    ],
    "gpt-5.4-mini": [
        "lost_update",
        "async_race_lock",
        "feature_flag_drift",
        "cache_invalidation_order",
        "partial_rollback_c",
    ],
}

# Expected results from original table (pass rates as fractions)
# Format: (case_id, model) -> {condition: expected_rate}
EXPECTED = {
    ("lost_update", "gpt-5.4-mini"):
        {"baseline_v2": 0.69, "leg_reduction_v2": 1.00, "leg_reduction_lean_v2": 0.92},
    ("cache_invalidation_order", "gpt-4.1-nano"):
        {"baseline_v2": 0.59, "leg_reduction_v2": 0.94, "leg_reduction_lean_v2": 1.00},
    ("partial_rollback_c", "gpt-5-mini"):
        {"baseline_v2": 0.14, "leg_reduction_v2": 0.77, "leg_reduction_lean_v2": 0.70},
    ("partial_rollback_b", "gpt-5-mini"):
        {"baseline_v2": 0.60, "leg_reduction_v2": 0.84, "leg_reduction_lean_v2": 0.84},
    ("mutable_default_b", "gpt-4.1-nano"):
        {"baseline_v2": 0.46, "leg_reduction_v2": 0.82, "leg_reduction_lean_v2": 1.00},
    ("effect_order_c", "gpt-5-mini"):
        {"baseline_v2": 0.18, "leg_reduction_v2": 0.23, "leg_reduction_lean_v2": 0.36},
    ("l3_state_pipeline", "gpt-5-mini"):
        {"baseline_v2": 0.72, "leg_reduction_v2": 0.88, "leg_reduction_lean_v2": 0.82},
    ("lost_update", "gpt-4.1-nano"):
        {"baseline_v2": 0.18, "leg_reduction_v2": 0.31, "leg_reduction_lean_v2": 0.27},
    ("lost_update", "gpt-4o-mini"):
        {"baseline_v2": 0.38, "leg_reduction_v2": 0.52, "leg_reduction_lean_v2": 0.28},
    ("hidden_dep_multihop", "gpt-4o-mini"):
        {"baseline_v2": 0.08, "leg_reduction_v2": 0.96, "leg_reduction_lean_v2": 0.86},
    ("invariant_partial_fail", "gpt-5-mini"):
        {"baseline_v2": 0.12, "leg_reduction_v2": 0.36, "leg_reduction_lean_v2": 0.82},
    ("false_fix_deadlock", "gpt-5-mini"):
        {"baseline_v2": 0.08, "leg_reduction_v2": 0.36},
    ("check_then_act", "gpt-4.1-nano"):
        {"baseline_v2": 0.12, "leg_reduction_v2": 0.34, "leg_reduction_lean_v2": 0.12},
    ("hidden_dep_multihop", "gpt-5-mini"):
        {"baseline_v2": 0.48, "leg_reduction_v2": 0.50, "leg_reduction_lean_v2": 0.86},
    ("alias_config_c", "gpt-4.1-nano"):
        {"baseline_v2": 1.00, "leg_reduction_v2": 0.02, "leg_reduction_lean_v2": 0.00},
    ("alias_config_c", "gpt-4o-mini"):
        {"baseline_v2": 1.00, "leg_reduction_v2": 0.48, "leg_reduction_lean_v2": 1.00},
    ("stale_cache_a", "gpt-4o-mini"):
        {"baseline_v2": 1.00, "leg_reduction_v2": 0.42},
    ("hidden_dep_multihop", "gpt-4.1-nano"):
        {"baseline_v2": 0.88, "leg_reduction_v2": 0.72, "leg_reduction_lean_v2": 0.24},
    ("async_race_lock", "gpt-5.4-mini"):
        {"baseline_v2": 0.00, "leg_reduction_v2": 0.00},
    ("feature_flag_drift", "gpt-5.4-mini"):
        {"baseline_v2": 0.62, "leg_reduction_v2": 0.67, "leg_reduction_lean_v2": 0.50},
    ("cache_invalidation_order", "gpt-5.4-mini"):
        {"baseline_v2": 0.40, "leg_reduction_v2": 0.44, "leg_reduction_lean_v2": 0.56},
    ("partial_rollback_c", "gpt-5.4-mini"):
        {"baseline_v2": 0.84, "leg_reduction_v2": 0.82, "leg_reduction_lean_v2": 0.98},
}

CONDITIONS = ["baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"]

_stop = False


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def create_case_files(all_cases, tmp_dir):
    """Create per-model case JSON files in tmp_dir."""
    case_by_id = {c["id"]: c for c in all_cases}
    paths = {}
    for model, case_ids in MODEL_CASES.items():
        cases = []
        for cid in case_ids:
            if cid not in case_by_id:
                print(f"  WARNING: case {cid} not found in cases_v2.json")
                continue
            cases.append(case_by_id[cid])
        short = model.replace(".", "").replace("-", "")
        path = Path(tmp_dir) / f"cases_{short}.json"
        with open(path, "w") as f:
            json.dump(cases, f, indent=2)
        paths[model] = str(path)
        print(f"  {model}: {len(cases)} cases -> {path.name}")
    return paths


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=None,
                        help="Only run these models (default: all)")
    cli = parser.parse_args()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_verify50_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    # Load all cases
    cases_path = Path(__file__).parent.parent / "cases_v2.json"
    all_cases = json.loads(cases_path.read_text())

    # Filter models if specified
    models_to_run = MODEL_CASES
    if cli.models:
        models_to_run = {m: v for m, v in MODEL_CASES.items()
                         if any(f in m for f in cli.models)}

    print("=" * 70)
    print("VERIFICATION: 50-trial results table")
    print("=" * 70)

    # Create per-model case files
    print("\nCase files:")
    case_file_paths = create_case_files(all_cases, tmp_dir)

    # Build all jobs: (model, trial) pairs
    jobs = []
    for model in models_to_run:
        n_cases = len(MODEL_CASES[model])
        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            short = model.replace(".", "").replace("-", "")
            cfg["run"]["trial"] = trial
            cfg["run"]["run_id"] = f"v_{short}_t{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["models"]["generation"][0]["name"] = model
            cfg["execution"]["num_workers"] = min(
                WORKERS_PER_PROCESS, n_cases)
            cfg["cases"]["source"] = case_file_paths[model]

            # Ensure all 3 conditions
            cfg["conditions"] = {
                c: {"retry": {"enabled": False}}
                for c in CONDITIONS
            }

            trial_config = Path(tmp_dir) / f"{short}_t{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            jobs.append((f"{model}_t{trial}", short, trial,
                         trial_config))

    total_evals = sum(
        len(MODEL_CASES[m]) * len(CONDITIONS) * N_TRIALS
        for m in MODEL_CASES
    )

    print(f"\n  Models: {list(MODEL_CASES.keys())}")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Max parallel: {MAX_PARALLEL}")
    print(f"  Workers/process: {WORKERS_PER_PROCESS}")
    print(f"  Jobs: {len(jobs)}")
    print(f"  Total evals: {total_evals}")
    print()

    t0 = time.monotonic()
    active = {}  # pid -> (name, proc, stdout_fh, stderr_fh)
    failures = []
    done_count = 0

    def reap_finished():
        nonlocal done_count
        finished = []
        for pid, (name, proc, so, se) in active.items():
            ret = proc.poll()
            if ret is not None:
                finished.append(pid)
                so.close()
                se.close()
                if ret == 0:
                    done_count += 1
                else:
                    failures.append(name)
                    print(f"  FAIL {name} (exit {ret})")
        for pid in finished:
            del active[pid]

    job_idx = 0
    last_status = time.monotonic()
    while job_idx < len(jobs) or active:
        if _stop:
            print("\nStopping — sending SIGTERM to active...")
            for pid, (name, proc, so, se) in active.items():
                proc.terminate()
            for pid, (name, proc, so, se) in active.items():
                proc.wait(timeout=30)
                so.close()
                se.close()
            break

        while job_idx < len(jobs) and len(active) < MAX_PARALLEL:
            name, short, trial, trial_config = jobs[job_idx]
            job_idx += 1

            stdout_f = open(
                LOG_DIR / f"{short}_t{trial}_stdout.log", "w")
            stderr_f = open(
                LOG_DIR / f"{short}_t{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py",
                   "--config", str(trial_config)]
            proc = subprocess.Popen(
                cmd, stdout=stdout_f, stderr=stderr_f)
            active[proc.pid] = (name, proc, stdout_f, stderr_f)

        # Periodic status (every 60s)
        now = time.monotonic()
        if now - last_status > 60:
            elapsed = now - t0
            print(f"  [{elapsed/60:.0f}m] "
                  f"{done_count}/{len(jobs)} done, "
                  f"{len(active)} active, "
                  f"{len(failures)} failed")
            last_status = now

        time.sleep(2)
        reap_finished()

    elapsed = time.monotonic() - t0
    print(f"\n  All jobs finished in {elapsed:.1f}s ({elapsed/60:.1f}m)")
    print(f"  Done: {done_count}, Failed: {len(failures)}")

    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f_name in failures:
            print(f"    {f_name}")

    # ── Aggregate & compare ──
    print(f"\n{'=' * 70}")
    print("AGGREGATING RESULTS")
    print(f"{'=' * 70}")

    case_model_cond = defaultdict(list)
    total = 0

    for ef in Path(LOG_DIR).rglob("events.jsonl"):
        for line in open(ef):
            ev = json.loads(line)
            if ev.get("event_type") != "case.end":
                continue
            total += 1
            cid = ev.get("case_id")
            cond = ev.get("condition")
            model = ev.get("model")
            p = ev.get("payload", {})
            passed = p.get("pass", False)
            case_model_cond[(cid, model, cond)].append(passed)

    print(f"  Total case.end events: {total}")

    # Compare with expected
    print(f"\n{'=' * 70}")
    print(f"{'Case x Model':45s} {'Cond':30s} "
          f"{'Orig':>6s} {'Verif':>6s} {'Delta':>7s} {'Flag':>6s}")
    print(f"{'-' * 70}")

    discrepancies = []
    for (case_id, model), expected_conds in sorted(EXPECTED.items()):
        for cond, expected_rate in sorted(expected_conds.items()):
            key = (case_id, model, cond)
            results = case_model_cond.get(key, [])
            n = len(results)
            if n == 0:
                print(f"  {case_id} x {model:15s} {cond:30s} "
                      f"{expected_rate:5.0%}  NO DATA")
                discrepancies.append(
                    (case_id, model, cond, expected_rate, None,
                     "NO DATA"))
                continue

            actual_rate = sum(results) / n
            delta = actual_rate - expected_rate
            # Flag if delta > 10 percentage points
            flag = ""
            if abs(delta) > 0.10:
                flag = "**"
                discrepancies.append(
                    (case_id, model, cond, expected_rate,
                     actual_rate, f"delta={delta:+.0%}"))
            elif abs(delta) > 0.05:
                flag = "*"

            short_model = (model.replace("gpt-", "")
                           .replace(".", "")
                           .replace("-", ""))
            label = f"{case_id} x {short_model}"
            print(f"  {label:45s} {cond:30s} "
                  f"{expected_rate:5.0%} {actual_rate:5.0%} "
                  f"{delta:+6.0%} {flag:>6s}")

    print(f"\n{'=' * 70}")
    if discrepancies:
        print(f"DISCREPANCIES (>10pp): {len(discrepancies)}")
        for case_id, model, cond, exp, act, reason in discrepancies:
            act_str = f"{act:.0%}" if act is not None else "N/A"
            print(f"  {case_id} x {model} / {cond}: "
                  f"expected {exp:.0%}, got {act_str} ({reason})")
    else:
        print("NO DISCREPANCIES >10pp. Results verified.")

    print(f"\n{'=' * 70}")

    # Write summary to file
    summary_path = LOG_DIR / "verification_summary.txt"
    with open(summary_path, "w") as sf:
        sf.write(f"Verification run: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        sf.write(f"Total evals: {total}/{total_evals}\n")
        sf.write(f"Elapsed: {elapsed:.1f}s\n")
        sf.write(f"Failures: {len(failures)}\n")
        sf.write(f"Discrepancies >10pp: {len(discrepancies)}\n\n")
        for case_id, model, cond, exp, act, reason in discrepancies:
            act_str = f"{act:.0%}" if act is not None else "N/A"
            sf.write(f"  {case_id} x {model} / {cond}: "
                     f"expected {exp:.0%}, got {act_str} ({reason})\n")
    print(f"  Summary written to {summary_path}")


if __name__ == "__main__":
    main()
