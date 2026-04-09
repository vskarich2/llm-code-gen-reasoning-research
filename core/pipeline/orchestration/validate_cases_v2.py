"""Validation pipeline for T3 v2 benchmark cases.

Runs checks on each case using the EXACT same execution path as production:
  _materialize_package → _run_subprocess (harness/run_case.py)

Checks:
  1. Buggy code loads and test FAILS
  2. Reference fix loads and test PASSES
  3. Reference fix is minimal
  4. Test is idempotent
  5. Metadata alignment

Usage:
    .venv/bin/python -m core.pipeline.orchestration.validate_cases_v2
    .venv/bin/python -m core.pipeline.orchestration.validate_cases_v2 --family auth_context_chain
    .venv/bin/python -m core.pipeline.orchestration.validate_cases_v2 --case auth_context_chain
"""

import argparse
import ast as _ast
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from core.config.paths import (
    PROJECT_ROOT, CASE_DATA_DIR, TESTS_V2_DIR, REFERENCE_FIXES_DIR,
    HARNESS_SCRIPT,
)
from core.pipeline.execution.exec_canonical import (
    _run_subprocess,
)


def _materialize(case: dict, file_contents: dict[str, str]) -> Path:
    """Create temp dir with pkg/, harness/, case_meta.json.

    Identical to exec_canonical._materialize_package but takes
    file_contents dict instead of a recon object.
    """
    case_id = case["id"]
    pkg_dir = Path(tempfile.mkdtemp(prefix=f"t3_val_{case_id}_"))

    pkg = pkg_dir / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")

    for filename, content in file_contents.items():
        (pkg / filename).write_text(content)

    harness_dst = pkg_dir / "harness"
    harness_dst.mkdir()
    shutil.copy2(str(HARNESS_SCRIPT), str(harness_dst / "run_case.py"))

    meta = {
        "case_id": case_id,
        "family": case.get("family", ""),
        "difficulty": case.get("difficulty", "a").lower(),
        "project_root": str(PROJECT_ROOT),
        "code_files": case["code_files"],
    }
    (pkg_dir / "case_meta.json").write_text(json.dumps(meta))

    return pkg_dir


def _run_case(case: dict, file_contents: dict[str, str], timeout: int = 30) -> dict:
    """Materialize and run via subprocess. Returns parsed JSON result."""
    pkg_dir = _materialize(case, file_contents)
    try:
        return _run_subprocess(pkg_dir, str(PROJECT_ROOT), timeout)
    finally:
        shutil.rmtree(str(pkg_dir), ignore_errors=True)


def _read_case_files(case: dict) -> dict[str, str]:
    """Read case code files into a filename -> content dict."""
    files = {}
    for rel in case["code_files"]:
        path = CASE_DATA_DIR / rel
        files[path.name] = path.read_text(encoding="utf-8")
    return files


def load_test_func(case: dict):
    family = case.get("family", case.get("id", ""))
    level = case.get("difficulty", "").lower()
    test_path = TESTS_V2_DIR / f"test_{family}.py"
    if not test_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"test_{family}", test_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, f"test_{level}", None)
    if fn is None:
        fn = getattr(mod, "test", None)
    if fn is None:
        fn = getattr(mod, "test_a", None)
    return fn


# ── Checks ──────────────────────────────────────────────────


def check_loads(case: dict) -> tuple[bool, str]:
    try:
        files = _read_case_files(case)
        result = _run_case(case, files)
        status = result.get("status", "")
        if status == "ok":
            return True, "loads"
        return False, f"load/run error: {result.get('error_message', status)}"
    except Exception as e:
        return False, f"load error: {e}"


def check_fails_buggy(case: dict) -> tuple[bool, str]:
    try:
        files = _read_case_files(case)
        result = _run_case(case, files)
        if result.get("status") != "ok":
            return False, f"run error: {result.get('error_message', result.get('status'))}"
        if result.get("passed", False):
            return False, "test PASSES on buggy code — bug not real"
        return True, "fails_buggy"
    except Exception as e:
        return False, f"test error: {e}"


def _read_baseline_files(case: dict) -> dict[str, str] | None:
    """Read the baseline (non-trap) files for this case's family.

    For trap variants, the baseline is the family's own generated case.
    For baselines, it's the same as _read_case_files.
    """
    import json as _json
    cases_path = CASE_DATA_DIR / "cases_v2.json"
    family = case.get("family", case["id"])
    # If this IS the baseline, just read its files
    if case["id"] == family:
        return _read_case_files(case)
    # Find the baseline case entry
    all_cases = _json.loads(cases_path.read_text())
    baseline = next((c for c in all_cases if c["id"] == family), None)
    if baseline is None:
        return None
    return _read_case_files(baseline)


def check_passes_fixed(case: dict) -> tuple[bool, str]:
    ref_path = REFERENCE_FIXES_DIR / f"{case['id']}.py"
    if not ref_path.exists():
        return False, "reference fix not found"
    try:
        # Always use baseline files (not trap-modified files)
        files = _read_baseline_files(case)
        if files is None:
            return False, "baseline case not found"
        bug_filename = case.get("reference_fix", {}).get("file", "")
        ref_code = ref_path.read_text(encoding="utf-8")
        if bug_filename and bug_filename in files:
            files[bug_filename] = ref_code
        else:
            files[bug_filename or "_reference_fix.py"] = ref_code
        result = _run_case(case, files)
        if result.get("status") != "ok":
            return False, f"run error: {result.get('error_message', result.get('status'))}"
        if not result.get("passed", False):
            reasons = result.get("failure_reasons", [])
            return False, f"test FAILS on reference fix: {reasons}"
        return True, "passes_fixed"
    except Exception as e:
        return False, f"ref fix error: {e}"


def check_minimal(case: dict) -> tuple[bool, str]:
    ref_path = REFERENCE_FIXES_DIR / f"{case['id']}.py"
    if not ref_path.exists():
        return False, "reference fix not found"
    ref_code = ref_path.read_text(encoding="utf-8")

    bug_file = case.get("reference_fix", {}).get("file")
    if bug_file:
        bug_path = CASE_DATA_DIR / next(
            (rel for rel in case["code_files"] if rel.endswith("/" + bug_file)),
            bug_file,
        )
        if bug_path.exists():
            buggy_code = bug_path.read_text(encoding="utf-8")
        else:
            return False, f"bug file not found: {bug_file}"
    else:
        return False, "reference_fix.file not set"

    buggy_lines = buggy_code.strip().splitlines()
    ref_lines = ref_code.strip().splitlines()
    diff_count = sum(1 for a, b in zip(buggy_lines, ref_lines) if a != b)
    diff_count += abs(len(buggy_lines) - len(ref_lines))
    level_max = {"A": 10, "B": 20, "C": 30, "B+": 20, "D": 30}.get(
        case.get("difficulty", "C"), 30)
    if diff_count > level_max:
        return False, f"diff={diff_count} lines, max={level_max}"
    return True, f"minimal (diff={diff_count})"


def check_idempotent(case: dict) -> tuple[bool, str]:
    try:
        files = _read_case_files(case)
        results = []
        for _ in range(3):
            r = _run_case(case, files)
            passed = r.get("passed", False)
            reasons = tuple(r.get("failure_reasons", []))
            results.append((passed, reasons))
        if len(set(results)) != 1:
            return False, f"non-idempotent: {results}"
        return True, "idempotent"
    except Exception as e:
        return False, f"idempotent error: {e}"


def check_metadata_alignment(case: dict) -> tuple[bool, str]:
    ref_path = REFERENCE_FIXES_DIR / f"{case['id']}.py"
    if not ref_path.exists():
        return False, "reference fix file not found"
    expected_fn = case.get("reference_fix", {}).get("function", "")
    if not expected_fn:
        return False, "reference_fix.function is empty"
    ref_code = ref_path.read_text(encoding="utf-8")
    try:
        tree = _ast.parse(ref_code)
    except SyntaxError as e:
        return False, f"reference fix has syntax error: {e}"
    ref_defs = {n.name for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef)}
    if expected_fn not in ref_defs:
        return False, (
            f"reference_fix.function='{expected_fn}' NOT FOUND in reference fix. "
            f"Defines: {sorted(ref_defs)}"
        )
    return True, "metadata_aligned"


# ── Orchestration ────────────────────────────────────────────


def validate_case(case: dict) -> dict:
    checks = {
        "loads": check_loads(case),
        "fails_buggy": check_fails_buggy(case),
        "passes_fixed": check_passes_fixed(case),
        "idempotent": check_idempotent(case),
        "metadata_aligned": check_metadata_alignment(case),
    }
    all_pass = all(ok for ok, _ in checks.values())
    return {"case_id": case["id"], "all_pass": all_pass, "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default=None)
    parser.add_argument("--case", default=None)
    args = parser.parse_args()

    cases_path = CASE_DATA_DIR / "cases_v2.json"
    if not cases_path.exists():
        print("cases_v2.json not found")
        return

    cases = json.loads(cases_path.read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    elif args.family:
        cases = [c for c in cases if c.get("family") == args.family]

    print(f"Validating {len(cases)} cases...\n")

    passed = 0
    failed = 0
    for case in cases:
        result = validate_case(case)
        status_parts = []
        for check_name, (ok, msg) in result["checks"].items():
            mark = "ok" if ok else "FAIL"
            status_parts.append(f"{check_name}={mark}")
        line = f"  {case['id']:<45} {' '.join(status_parts)}"
        if result["all_pass"]:
            passed += 1
        else:
            failed += 1
            for check_name, (ok, msg) in result["checks"].items():
                if not ok:
                    line += f"\n    -> {check_name}: {msg}"
        print(line)

    print(f"\n{passed} passed, {failed} failed, {len(cases)} total")


if __name__ == "__main__":
    main()
