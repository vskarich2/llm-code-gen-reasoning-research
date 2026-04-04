"""Canonical 4-model 10-trial ablation on all 58 cases.

4 models × 58 cases × 3 conditions × 10 trials = 6,960 evals.
All 40 trial processes (10 per model) run concurrently, each with 6 workers.
"""

import json
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_CONFIG = "config_storage/v2_canonical_revalidation.yaml"
MODELS = ["gpt-4.1-nano", "gpt-4o-mini", "gpt-5-mini", "gpt-5.4-mini"]
N_TRIALS = 10
LOG_DIR = Path("logs/v2_canonical_4model_10trial")
MAX_PARALLEL = 8

_stop = False


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def main():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="t3_4m10t_")

    with open(BASE_CONFIG) as f:
        base_cfg = yaml.safe_load(f)

    total_evals = len(MODELS) * 58 * 3 * N_TRIALS
    print(f"Canonical 4-model 10-trial ablation")
    print(f"  Models: {MODELS}")
    print(f"  Cases: all 58")
    print(f"  Conditions: baseline_v2, leg_reduction_v2, leg_reduction_lean_v2")
    print(f"  Trials: {N_TRIALS}")
    print(f"  Max parallel: {MAX_PARALLEL}")
    print(f"  Total evaluations: {total_evals}")
    print(f"  Output: {LOG_DIR}")
    print()

    # Build all job config_storage up front
    jobs = []
    for model in MODELS:
        for trial in range(1, N_TRIALS + 1):
            cfg = yaml.safe_load(yaml.dump(base_cfg))
            cfg["run"]["trial"] = trial
            short = model.replace(".", "").replace("-", "")
            cfg["run"]["run_id"] = f"{short}_t{trial}"
            cfg["run"]["run_dir"] = str(LOG_DIR)
            cfg["models"]["generation"][0]["name"] = model
            cfg["execution"]["num_workers"] = 6
            cfg["cases"]["source"] = "cases_v2.json"

            trial_config = Path(tmp_dir) / f"{short}_t{trial}.yaml"
            with open(trial_config, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)

            jobs.append((f"{model}_t{trial}", short, trial,
                         trial_config))

    print(f"  {len(jobs)} jobs queued")
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
                    print(f"  OK   {name}")
                else:
                    failures.append(name)
                    print(f"  FAIL {name} (exit {ret})")
        for pid in finished:
            del active[pid]

    job_idx = 0
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
            print(f"  [LAUNCH] {name} (PID {proc.pid})")

        time.sleep(2)
        reap_finished()

    elapsed = time.monotonic() - t0
    print(f"\n  Done in {elapsed:.1f}s")

    if failures:
        print(f"\n  FAILURES: {len(failures)}/{len(jobs)}")

    # Aggregate
    from collections import Counter, defaultdict

    case_model_cond = defaultdict(list)
    cats = Counter()
    recon_cats = Counter()
    recursion = 0
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
            cat = p.get("execution_category", "?")
            recon = p.get("reconstruction_status", "?")
            case_model_cond[(cid, model, cond)].append(passed)
            cats[cat] += 1
            recon_cats[recon] += 1
            if any("recursion" in str(r).lower()
                   for r in p.get("reasons", [])):
                recursion += 1

    total_pass = sum(sum(v) for v in case_model_cond.values())

    print(f"\n{'=' * 70}")
    print(f"  RESULTS: {total}/{total_evals} evals")
    print(f"  Pass: {total_pass}, Fail: {total - total_pass}")
    print(f"  RecursionErrors: {recursion}")
    print(f"{'=' * 70}")

    print(f"\n  Execution categories:")
    for k, v in cats.most_common():
        print(f"    {k}: {v}")

    print(f"\n  Reconstruction statuses:")
    for k, v in recon_cats.most_common():
        print(f"    {k}: {v}")

    print(f"\n  Per-model pass rates:")
    for model in MODELS:
        mrows = [(k, v) for k, v in case_model_cond.items()
                 if k[1] == model]
        mp = sum(sum(v) for _, v in mrows)
        mt = sum(len(v) for _, v in mrows)
        print(f"    {model:15s}  {mp}/{mt} ({100*mp/mt:.1f}%)"
              if mt else f"    {model:15s}  no data")

    print(f"\n  Per-model × condition:")
    for model in MODELS:
        print(f"  {model}:")
        for cond in ["baseline_v2", "leg_reduction_v2",
                      "leg_reduction_lean_v2"]:
            rows = [(k, v) for k, v in case_model_cond.items()
                    if k[1] == model and k[2] == cond]
            mp = sum(sum(v) for _, v in rows)
            mt = sum(len(v) for _, v in rows)
            print(f"    {cond:30s}  {mp}/{mt} ({100*mp/mt:.1f}%)"
                  if mt else f"    {cond:30s}  no data")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    main()
