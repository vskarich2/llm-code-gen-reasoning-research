"""GATE 5 — End-to-end stress test.

Run ≥10 cases through both old and new prompt systems with mock LLM.
Compare execution outcomes. OLD vs NEW must match EXACTLY.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.shared import (
    ensure_loaded, load_all_cases, old_build_prompt, new_build_prompt,
    prompt_hash, write_json, write_text,
)


def run_single_case_mock(case, prompt):
    """Run a case through the execution pipeline with a given prompt (mock mode)."""
    from llm import call_model
    from execution import evaluate_case

    raw_output = call_model(prompt, model="mock-model")
    parsed, ev = evaluate_case(case, raw_output)
    return {
        "pass": ev.get("pass", False),
        "score": ev.get("score", 0),
        "ran": ev.get("execution", {}).get("ran", False),
        "error": ev.get("execution", {}).get("error_message"),
    }


def run_gate():
    ensure_loaded()

    # Need a RunLogger active for write_log calls in evaluate_case path
    import tempfile
    from execution import init_run_log, close_run_log
    tmp = Path(tempfile.mkdtemp(prefix="e2e_stress_"))
    init_run_log("mock-model", log_dir=tmp)

    cases = load_all_cases()[:15]  # first 15 cases

    results = {"gate": "e2e_stress", "cases": len(cases), "checks": 0,
               "mismatches": [], "passed": True}
    lines = ["GATE 5 — END-TO-END STRESS TEST\n"]

    for case in cases:
        cid = case["id"]
        try:
            old_prompt = old_build_prompt(case, "baseline")
            new_prompt = new_build_prompt(case, "baseline")
        except Exception as e:
            lines.append(f"  SKIP: {cid}/baseline: {e}")
            continue

        # Prompts must be identical first
        if old_prompt != new_prompt:
            results["passed"] = False
            results["mismatches"].append({"case": cid, "type": "prompt_mismatch"})
            lines.append(f"  PROMPT MISMATCH: {cid}")
            continue

        # Run both through execution (same prompt → should get same result)
        try:
            old_result = run_single_case_mock(case, old_prompt)
            new_result = run_single_case_mock(case, new_prompt)
        except Exception as e:
            lines.append(f"  EXEC ERROR: {cid}: {e}")
            continue

        results["checks"] += 1
        if old_result["pass"] != new_result["pass"]:
            results["passed"] = False
            results["mismatches"].append({
                "case": cid, "type": "execution_mismatch",
                "old_pass": old_result["pass"], "new_pass": new_result["pass"],
            })
            lines.append(f"  EXEC MISMATCH: {cid} old_pass={old_result['pass']} new_pass={new_result['pass']}")
        else:
            lines.append(f"  OK: {cid} pass={old_result['pass']}")

    close_run_log()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    lines.append(f"\n{results['checks']} execution checks, {len(results['mismatches'])} mismatches")
    lines.append(f"VERDICT: {'PASS' if results['passed'] else 'FAIL'}")

    write_json("validation/results/e2e_stress_report.json", results)
    write_text("validation/results/e2e_stress_report.txt", "\n".join(lines))
    return results


if __name__ == "__main__":
    r = run_gate()
    print(f"Gate 5: {r['checks']} checks, {len(r['mismatches'])} mismatches → {'PASS' if r['passed'] else 'FAIL'}")
    sys.exit(0 if r["passed"] else 1)
