"""Verify 3 models on 6 recursion-contaminated cases, 10 trials each.

3 models × 6 cases × 3 conditions × 10 trials = 540 evals.
All 30 trial processes (10 per model) run concurrently, each with 6 workers.
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
MODELS = ["gpt-4.1-nano", "gpt-4o-mini", "gpt-5.4-mini"]
CASES = [
    "effect_order_b", "effect_order_c",
    "retry_dup_b", "retry_dup_c",
    "partial_rollback_b", "partial_rollback_c",
]
N_TRIALS = 10
LOG_DIR = Path("logs/v2_canonical_verify_3models")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_verify3_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    # Write cases file with only the 6 target cases
    all_cases = json.load(open("cases_v2.json"))
    target_cases = [c for c in all_cases if c["id"] in CASES]
    cases_file = Path(tmp_dir) / "verify_cases.json"
    cases_file.write_text(json.dumps(target_cases, indent=2))

    total_evals = len(MODELS) * len(CASES) * 3 * N_TRIALS
    print(f"Canonical Verification: 3 models")
    print(f"  Models: {MODELS}")
    print(f"  Cases: {CASES}")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Total evaluations: {total_evals}")
    print(f"  Output: {LOG_DIR}")
    print()

    procs = []
    t0 = time.monotonic()

    for model in MODELS:
        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            cfg["run"]["trial"] = trial
            cfg["run"]["run_id"] = f"verify_{model.replace('.', '')}_{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["models"]["generation"][0]["name"] = model
            cfg["execution"]["num_workers"] = 6
            cfg["cases"]["source"] = str(cases_file)

            trial_config = Path(tmp_dir) / f"verify_{model}_{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            stdout_f = open(
                LOG_DIR / f"verify_{model}_{trial}_stdout.log", "w")
            stderr_f = open(
                LOG_DIR / f"verify_{model}_{trial}_stderr.log", "w")

            cmd = [sys.executable, "runner.py",
                   "--config", str(trial_config)]
            proc = subprocess.Popen(cmd, stdout=stdout_f, stderr=stderr_f)
            procs.append((f"{model}_t{trial}", proc, stdout_f, stderr_f))

    print(f"  Launched {len(procs)} trial processes")
    print()

    # Wait
    failures = []
    for name, proc, so, se in procs:
        proc.wait()
        so.close()
        se.close()
        if proc.returncode != 0:
            failures.append(name)
            print(f"  FAIL {name} (exit {proc.returncode})")
        else:
            print(f"  OK   {name}")

    elapsed = time.monotonic() - t0
    print(f"\n  Done in {elapsed:.1f}s")

    if failures:
        print(f"\n  FAILURES: {failures}")

    # Aggregate
    from collections import defaultdict

    case_model_cond = defaultdict(list)
    recursion = 0

    for ef in Path(LOG_DIR).rglob("events.jsonl"):
        for line in open(ef):
            ev = json.loads(line)
            if ev.get("event_type") != "case.end":
                continue
            cid = ev.get("case_id")
            cond = ev.get("condition")
            model = ev.get("model")
            p = ev.get("payload", {})
            passed = p.get("pass", False)
            case_model_cond[(cid, model, cond)].append(passed)
            if any("recursion" in str(r).lower()
                   for r in p.get("reasons", [])):
                recursion += 1

    total = sum(len(v) for v in case_model_cond.values())
    total_pass = sum(sum(v) for v in case_model_cond.values())

    print(f"\n{'=' * 70}")
    print(f"  VERIFICATION RESULTS: {total} evals, {recursion} RecursionErrors")
    print(f"{'=' * 70}")

    for model in MODELS:
        print(f"\n  {model}:")
        print(f"  {'case':25s} {'baseline':>10s} {'leg_v2':>10s}"
              f" {'lean':>10s}  {'total':>8s}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}  {'-'*8}")
        for cid in CASES:
            parts = []
            tp, tn = 0, 0
            for cond in ["baseline_v2", "leg_reduction_v2",
                          "leg_reduction_lean_v2"]:
                results = case_model_cond.get(
                    (cid, model, cond), [])
                p = sum(results)
                tp += p
                tn += len(results)
                parts.append(f"{p}/{len(results)}")
            print(f"  {cid:25s} {parts[0]:>10s} {parts[1]:>10s}"
                  f" {parts[2]:>10s}  {tp}/{tn}")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    main()
