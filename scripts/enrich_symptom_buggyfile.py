"""Enrich cases_v2_all_data.json with symptom and buggy_file fields.

Uses the REAL exec_canonical materialization + subprocess harness,
identical to how the benchmark runs in production.

Run: .venv/bin/python scripts/enrich_symptom_buggyfile.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CASES_PATH = Path("case_data/cases_v2_all_data.json")
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
HARNESS_SCRIPT = Path(PROJECT_ROOT) / "core" / "harness" / "run_case.py"


def identify_buggy_file(case):
    """Identify the single buggy file from reference_fix.file."""
    rf = case.get("reference_fix", {})
    rf_file = rf.get("file", "")
    if rf_file:
        full_path = Path("case_data") / rf_file
        if full_path.exists():
            return rf_file, full_path
    code_files = case.get("code_files", [])
    if len(code_files) == 1:
        full_path = Path("case_data") / code_files[0]
        if full_path.exists():
            return code_files[0], full_path
    return None, None


def materialize_and_run(case):
    """Materialize buggy code into a temp package and run via subprocess harness.

    Replicates exec_canonical's materialization exactly.
    Returns the full subprocess JSON result dict.
    """
    cid = case["id"]
    family = case.get("family", cid)
    difficulty = case.get("difficulty", "a").lower()
    code_files = case.get("code_files", [])

    pkg_dir = Path(tempfile.mkdtemp(prefix=f"t3_symptom_{cid}_"))

    try:
        # pkg/
        pkg = pkg_dir / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        # Write ALL buggy code files
        for rel_path in code_files:
            full = Path("case_data") / rel_path
            if full.exists():
                filename = Path(rel_path).name
                (pkg / filename).write_text(full.read_text())

        # harness/
        harness_dst = pkg_dir / "harness"
        harness_dst.mkdir()
        shutil.copy2(str(HARNESS_SCRIPT), str(harness_dst / "run_case.py"))

        # case_meta.json
        meta = {
            "case_id": cid,
            "family": family,
            "difficulty": difficulty,
            "project_root": PROJECT_ROOT,
            "code_files": code_files,
        }
        (pkg_dir / "case_meta.json").write_text(json.dumps(meta))

        # Run subprocess
        env = os.environ.copy()
        case_data_dir = os.path.join(PROJECT_ROOT, "case_data")
        env["PYTHONPATH"] = f"{pkg}{os.pathsep}{PROJECT_ROOT}{os.pathsep}{case_data_dir}"

        proc = subprocess.run(
            [sys.executable, "harness/run_case.py"],
            cwd=str(pkg_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        if proc.returncode != 0:
            return {
                "status": "crash",
                "exit_code": proc.returncode,
                "stderr": (proc.stderr or "")[:500],
                "stdout": (proc.stdout or "")[:500],
            }

        try:
            return json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            return {
                "status": "invalid_output",
                "stdout": (proc.stdout or "")[:500],
                "stderr": (proc.stderr or "")[:500],
            }

    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "error_message": str(e)}
    finally:
        shutil.rmtree(pkg_dir, ignore_errors=True)


def extract_symptom(harness_result):
    """Extract a clean symptom string from the harness result."""
    status = harness_result.get("status", "error")

    if status == "timeout":
        return "TIMEOUT: test did not complete within 30s"

    if status == "crash":
        stderr = harness_result.get("stderr", "")
        # Extract last meaningful line from stderr
        lines = [l.strip() for l in stderr.strip().split("\n") if l.strip()]
        if lines:
            return f"CRASH: {lines[-1]}"
        return f"CRASH: exit_code={harness_result.get('exit_code')}"

    if status == "invalid_output":
        return f"INVALID_OUTPUT: {harness_result.get('stdout', '')[:200]}"

    if status == "error":
        err_type = harness_result.get("error_type", "Unknown")
        err_msg = harness_result.get("error_message", "")
        return f"{err_type}: {err_msg}"

    # status == "ok" — test ran
    passed = harness_result.get("passed", False)
    reasons = harness_result.get("failure_reasons", [])

    if passed:
        return "WARNING_BUGGY_PASSES: " + "; ".join(str(r) for r in reasons)

    if reasons:
        return "; ".join(str(r) for r in reasons)

    return "FAIL: no failure reasons provided"


def main():
    cases = json.loads(CASES_PATH.read_text())
    print(f"Loaded {len(cases)} cases from {CASES_PATH}")
    print(f"Harness: {HARNESS_SCRIPT}")
    print(f"Project root: {PROJECT_ROOT}")
    print()

    success = 0
    failures = []

    for case in cases:
        cid = case["id"]

        # 1. Identify buggy file
        buggy_rel, buggy_path = identify_buggy_file(case)
        if buggy_path is None:
            msg = f"cannot identify buggy file"
            print(f"  FAIL  {cid}: {msg}")
            failures.append((cid, msg))
            continue

        buggy_content = buggy_path.read_text()

        # 2. Run buggy code through real harness
        harness_result = materialize_and_run(case)

        # 3. Extract symptom
        symptom = extract_symptom(harness_result)

        passed = harness_result.get("passed", False)
        if passed:
            print(f"  WARN  {cid:35s} BUGGY PASSES! symptom={symptom[:80]}")
        else:
            print(f"  OK    {cid:35s} symptom={symptom[:80]}")

        # 4. Insert fields
        case["symptom"] = symptom
        case["buggy_file"] = buggy_content
        success += 1

    # Write back
    CASES_PATH.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"Total: {len(cases)}")
    print(f"Enriched: {success}")
    print(f"Failures: {len(failures)}")
    if failures:
        for cid, reason in failures:
            print(f"  FAILED: {cid} — {reason}")

    # Validation
    print(f"\nValidation:")
    reloaded = json.loads(CASES_PATH.read_text())
    missing_symptom = [c["id"] for c in reloaded if "symptom" not in c]
    missing_buggy = [c["id"] for c in reloaded if "buggy_file" not in c]
    empty_symptom = [c["id"] for c in reloaded if c.get("symptom") == ""]
    non_string_buggy = [c["id"] for c in reloaded
                        if "buggy_file" in c and not isinstance(c["buggy_file"], str)]
    buggy_passes = [c["id"] for c in reloaded
                    if c.get("symptom", "").startswith("WARNING_BUGGY_PASSES")]

    print(f"  Missing symptom:    {len(missing_symptom)} {missing_symptom}")
    print(f"  Missing buggy_file: {len(missing_buggy)} {missing_buggy}")
    print(f"  Empty symptom:      {len(empty_symptom)} {empty_symptom}")
    print(f"  Non-string buggy:   {len(non_string_buggy)} {non_string_buggy}")
    print(f"  Buggy passes test:  {len(buggy_passes)} {buggy_passes}")
    print(f"  JSON valid:         True")


if __name__ == "__main__":
    main()
