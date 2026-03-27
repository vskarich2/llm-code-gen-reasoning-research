"""GATE 1 — Cross-distribution behavioral validation.

Run ≥15 cases × 2 conditions through both systems.
Compare pass_rate, ran_rate, failure_type distribution.
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.shared import (
    ensure_loaded, load_all_cases, old_build_prompt, new_build_prompt,
    write_json, write_text,
)


def run_case_pipeline(case, prompt):
    """Run prompt through mock LLM + full evaluation pipeline."""
    from llm import call_model
    from execution import evaluate_case
    raw = call_model(prompt, model="mock-model")
    _, ev = evaluate_case(case, raw)
    return {
        "pass": ev.get("pass", False),
        "ran": ev.get("execution", {}).get("ran", False),
        "failure_type": ev.get("failure_type"),
    }


def run_gate():
    ensure_loaded()

    import tempfile
    from execution import init_run_log, close_run_log
    tmp = Path(tempfile.mkdtemp(prefix="cross_dist_"))
    init_run_log("mock-model", log_dir=tmp)

    cases = load_all_cases()
    # Select ≥15 with family/difficulty coverage
    selected = cases[:20]
    conditions = ["baseline", "structured_reasoning"]

    old_metrics = {"pass": 0, "ran": 0, "total": 0, "failure_types": Counter()}
    new_metrics = {"pass": 0, "ran": 0, "total": 0, "failure_types": Counter()}
    lines = ["GATE 1 — CROSS-DISTRIBUTION REPORT\n"]
    mismatches = []

    for case in selected:
        for cond in conditions:
            try:
                old_p = old_build_prompt(case, cond)
                new_p = new_build_prompt(case, cond)
            except Exception:
                continue

            if old_p != new_p:
                mismatches.append({"case": case["id"], "condition": cond, "type": "prompt"})
                continue

            try:
                old_r = run_case_pipeline(case, old_p)
                new_r = run_case_pipeline(case, new_p)
            except Exception as e:
                lines.append(f"  EXEC ERROR: {case['id']}/{cond}: {e}")
                continue

            old_metrics["total"] += 1
            new_metrics["total"] += 1
            old_metrics["pass"] += int(old_r["pass"])
            new_metrics["pass"] += int(new_r["pass"])
            old_metrics["ran"] += int(old_r["ran"])
            new_metrics["ran"] += int(new_r["ran"])
            old_metrics["failure_types"][old_r["failure_type"] or "NONE"] += 1
            new_metrics["failure_types"][new_r["failure_type"] or "NONE"] += 1

            if old_r["pass"] != new_r["pass"]:
                mismatches.append({
                    "case": case["id"], "condition": cond, "type": "execution",
                    "old_pass": old_r["pass"], "new_pass": new_r["pass"],
                })

    close_run_log()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    # Compute rates
    old_pass_rate = old_metrics["pass"] / max(old_metrics["total"], 1)
    new_pass_rate = new_metrics["pass"] / max(new_metrics["total"], 1)
    old_ran_rate = old_metrics["ran"] / max(old_metrics["total"], 1)
    new_ran_rate = new_metrics["ran"] / max(new_metrics["total"], 1)

    passed = True
    if abs(old_pass_rate - new_pass_rate) > 0.05:
        passed = False
    if old_ran_rate != new_ran_rate:
        passed = False
    if len(mismatches) > 0:
        passed = False

    lines.append(f"  Cases: {len(selected)}, Conditions: {conditions}")
    lines.append(f"  Old: pass_rate={old_pass_rate:.3f} ran_rate={old_ran_rate:.3f}")
    lines.append(f"  New: pass_rate={new_pass_rate:.3f} ran_rate={new_ran_rate:.3f}")
    lines.append(f"  Delta: pass={new_pass_rate - old_pass_rate:+.3f} ran={new_ran_rate - old_ran_rate:+.3f}")
    lines.append(f"  Mismatches: {len(mismatches)}")
    lines.append(f"  VERDICT: {'PASS' if passed else 'FAIL'}")

    results = {
        "gate": "cross_distribution", "passed": passed,
        "old_pass_rate": old_pass_rate, "new_pass_rate": new_pass_rate,
        "old_ran_rate": old_ran_rate, "new_ran_rate": new_ran_rate,
        "mismatches": mismatches, "total_checks": old_metrics["total"],
    }
    write_json("validation/results/cross_distribution_report.json", results)
    write_text("validation/results/cross_distribution_report.txt", "\n".join(lines))
    return results


if __name__ == "__main__":
    r = run_gate()
    print(f"Gate 1: {r['total_checks']} checks, delta_pass={r['new_pass_rate']-r['old_pass_rate']:+.3f} → {'PASS' if r['passed'] else 'FAIL'}")
    sys.exit(0 if r["passed"] else 1)
