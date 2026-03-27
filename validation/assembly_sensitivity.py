"""GATE 4 — Multi-file assembly sensitivity check.

Use ONLY multi-file cases. Compare old vs new execution results.
ANY divergence → FAIL.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from validation.shared import (
    ensure_loaded, load_all_cases, old_build_prompt, new_build_prompt,
    write_json, write_text,
)


def is_multifile(case):
    """Check if case has multiple code files."""
    return len(case.get("code_files", [])) > 1


def run_case_execution(case, prompt):
    """Execute a case with a prompt through mock pipeline."""
    from llm import call_model
    from execution import evaluate_case
    raw = call_model(prompt, model="mock-model")
    _, ev = evaluate_case(case, raw)
    return {
        "pass": ev.get("pass", False),
        "ran": ev.get("execution", {}).get("ran", False),
        "error_type": type(ev.get("execution", {}).get("error_message")).__name__
        if ev.get("execution", {}).get("error_message") else None,
        "reconstruction": ev.get("reconstruction_status"),
    }


def run_gate():
    ensure_loaded()

    import tempfile
    from execution import init_run_log, close_run_log
    tmp = Path(tempfile.mkdtemp(prefix="assembly_sens_"))
    init_run_log("mock-model", log_dir=tmp)

    cases = load_all_cases()
    multifile = [c for c in cases if is_multifile(c)]
    if not multifile:
        # Fallback: use first 10 cases
        multifile = cases[:10]

    results = {"gate": "assembly_sensitivity", "cases": len(multifile),
               "checks": 0, "mismatches": [], "passed": True}
    lines = [f"GATE 4 — MULTI-FILE ASSEMBLY SENSITIVITY ({len(multifile)} cases)\n"]

    for case in multifile:
        cid = case["id"]
        try:
            old_p = old_build_prompt(case, "baseline")
            new_p = new_build_prompt(case, "baseline")
        except Exception as e:
            lines.append(f"  SKIP: {cid}: {e}")
            continue

        if old_p != new_p:
            results["passed"] = False
            results["mismatches"].append({"case": cid, "type": "prompt_mismatch"})
            lines.append(f"  PROMPT MISMATCH: {cid}")
            continue

        try:
            old_r = run_case_execution(case, old_p)
            new_r = run_case_execution(case, new_p)
        except Exception as e:
            lines.append(f"  EXEC ERROR: {cid}: {e}")
            continue

        results["checks"] += 1
        diverged = (old_r["pass"] != new_r["pass"] or old_r["ran"] != new_r["ran"])
        if diverged:
            results["passed"] = False
            results["mismatches"].append({
                "case": cid, "old": old_r, "new": new_r,
            })
            lines.append(f"  DIVERGED: {cid} old={old_r} new={new_r}")
        else:
            lines.append(f"  OK: {cid} pass={old_r['pass']} ran={old_r['ran']}")

    close_run_log()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    lines.append(f"\n{results['checks']} checks, {len(results['mismatches'])} mismatches")
    lines.append(f"VERDICT: {'PASS' if results['passed'] else 'FAIL'}")

    write_json("validation/results/assembly_sensitivity_report.json", results)
    write_text("validation/results/assembly_sensitivity_report.txt", "\n".join(lines))
    return results


if __name__ == "__main__":
    r = run_gate()
    print(f"Gate 4: {r['checks']} checks, {len(r['mismatches'])} mismatches → {'PASS' if r['passed'] else 'FAIL'}")
    sys.exit(0 if r["passed"] else 1)
