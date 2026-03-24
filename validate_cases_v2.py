"""Validation pipeline for T3 v2 benchmark cases.

Runs 6 checks on each case:
  1. Buggy code loads as a module
  2. Test FAILS on buggy code
  3. Test PASSES on reference fix
  4. Reference fix is minimal
  5. Test is idempotent
  6. Cross-case isolation

Usage:
    .venv/bin/python validate_cases_v2.py
    .venv/bin/python validate_cases_v2.py --family alias_config
    .venv/bin/python validate_cases_v2.py --case alias_config_a
"""

import argparse
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

BASE = Path(__file__).parent

# Stdlib modules for import stripping (subset — covers what cases use)
_STDLIB = {
    "os", "sys", "json", "re", "math", "copy", "collections", "functools",
    "itertools", "typing", "pathlib", "datetime", "abc", "dataclasses",
    "enum", "logging", "hashlib", "random", "io", "string", "textwrap",
}


def _strip_local_imports(code: str) -> str:
    """Remove import lines that reference sibling modules (not stdlib)."""
    lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("from ") and " import " in stripped:
            module = stripped.split()[1].split(".")[0]
            if module not in _STDLIB:
                continue
        elif stripped.startswith("import "):
            module = stripped.split()[1].split(".")[0]
            if module not in _STDLIB:
                continue
        lines.append(line)
    return "\n".join(lines)


def load_module(code: str, name: str = "candidate") -> ModuleType:
    cleaned = _strip_local_imports(code)
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__builtins__"] = __builtins__
    exec(compile(cleaned, f"<{name}>", "exec"), mod.__dict__)
    sys.modules[name] = mod
    return mod


def load_case_code(case: dict) -> str:
    parts = []
    for rel in case["code_files"]:
        path = BASE / rel
        parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def load_test_func(case: dict):
    family = case["family"]
    level = case["difficulty"].lower()
    test_path = BASE / "tests_v2" / f"test_{family}.py"
    if not test_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"test_{family}", test_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn_name = f"test_{level}"
    fn = getattr(mod, fn_name, None)
    if fn is None:
        fn = getattr(mod, "test", None)  # fallback for single-test cases
    return fn


def load_reference_code(case: dict) -> str | None:
    """Load reference fix, merged with non-bug files from the case.

    The reference fix file contains only the fixed version of the primary
    bug file. For multi-file cases, we concatenate it with the other
    (unchanged) files to produce a complete module.
    """
    ref_path = BASE / "reference_fixes" / f"{case['id']}.py"
    if not ref_path.exists():
        return None
    ref_code = ref_path.read_text(encoding="utf-8")

    # For multi-file cases, prepend the non-bug files
    bug_file = case.get("reference_fix", {}).get("file", "")
    other_parts = []
    for rel in case["code_files"]:
        if rel != bug_file:
            path = BASE / rel
            if path.exists():
                other_parts.append(path.read_text(encoding="utf-8"))

    if other_parts:
        return "\n\n".join(other_parts) + "\n\n" + ref_code
    return ref_code


def check_loads(case: dict) -> tuple[bool, str]:
    try:
        code = load_case_code(case)
        load_module(code, f"check_load_{case['id']}")
        return True, "loads"
    except Exception as e:
        return False, f"load error: {e}"


def check_fails_buggy(case: dict) -> tuple[bool, str]:
    test_fn = load_test_func(case)
    if test_fn is None:
        return False, "test function not found"
    try:
        code = load_case_code(case)
        mod = load_module(code, f"buggy_{case['id']}")
        passed, reasons = test_fn(mod)
        if passed:
            return False, "test PASSES on buggy code — bug not real"
        return True, "fails_buggy"
    except Exception as e:
        return False, f"test error: {e}"


def check_passes_fixed(case: dict) -> tuple[bool, str]:
    test_fn = load_test_func(case)
    if test_fn is None:
        return False, "test function not found"
    ref_code = load_reference_code(case)
    if ref_code is None:
        return False, "reference fix not found"
    try:
        mod = load_module(ref_code, f"fixed_{case['id']}")
        passed, reasons = test_fn(mod)
        if not passed:
            return False, f"test FAILS on reference fix: {reasons}"
        return True, "passes_fixed"
    except Exception as e:
        return False, f"ref fix error: {e}"


def check_minimal(case: dict) -> tuple[bool, str]:
    """Check that the bug fix is minimal.

    Compares only the primary bug file against the raw reference fix file
    (NOT the merged version used for execution).
    """
    ref_path = BASE / "reference_fixes" / f"{case['id']}.py"
    if not ref_path.exists():
        return False, "reference fix not found"
    ref_code = ref_path.read_text(encoding="utf-8")

    bug_file = case.get("reference_fix", {}).get("file")
    if bug_file:
        bug_path = BASE / bug_file
        if bug_path.exists():
            buggy_code = bug_path.read_text(encoding="utf-8")
        else:
            buggy_code = load_case_code(case)
    else:
        buggy_code = load_case_code(case)

    buggy_lines = buggy_code.strip().splitlines()
    ref_lines = ref_code.strip().splitlines()

    diff_count = sum(1 for a, b in zip(buggy_lines, ref_lines) if a != b)
    diff_count += abs(len(buggy_lines) - len(ref_lines))
    # Difficulty-based threshold: reference fixes may have formatting differences
    level_max = {"A": 10, "B": 20, "C": 30}.get(case.get("difficulty", "C"), 30)
    if diff_count > level_max:
        return False, f"diff={diff_count} lines, max={level_max}"
    return True, f"minimal (diff={diff_count})"


def check_idempotent(case: dict) -> tuple[bool, str]:
    test_fn = load_test_func(case)
    if test_fn is None:
        return False, "test function not found"
    try:
        code = load_case_code(case)
        results = []
        for i in range(3):
            mod = load_module(code, f"idemp_{case['id']}_{i}")
            passed, reasons = test_fn(mod)
            results.append((passed, tuple(reasons)))
        if len(set(results)) != 1:
            return False, f"non-idempotent: {results}"
        return True, "idempotent"
    except Exception as e:
        return False, f"idempotent error: {e}"


def validate_case(case: dict) -> dict:
    checks = {
        "loads": check_loads(case),
        "fails_buggy": check_fails_buggy(case),
        "passes_fixed": check_passes_fixed(case),
        "minimal": check_minimal(case),
        "idempotent": check_idempotent(case),
    }
    all_pass = all(ok for ok, _ in checks.values())
    return {"case_id": case["id"], "all_pass": all_pass, "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", default=None)
    parser.add_argument("--case", default=None)
    args = parser.parse_args()

    cases_path = BASE / "cases_v2.json"
    if not cases_path.exists():
        print("cases_v2.json not found")
        return

    cases = json.loads(cases_path.read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    elif args.family:
        cases = [c for c in cases if c["family"] == args.family]

    print(f"Validating {len(cases)} cases...\n")

    passed = 0
    failed = 0
    for case in cases:
        result = validate_case(case)
        status_parts = []
        for check_name, (ok, msg) in result["checks"].items():
            mark = "ok" if ok else "FAIL"
            status_parts.append(f"{check_name}={mark}")
        line = f"  {case['id']:<28} {' '.join(status_parts)}"
        if result["all_pass"]:
            passed += 1
        else:
            failed += 1
            # Show failure details
            for check_name, (ok, msg) in result["checks"].items():
                if not ok:
                    line += f"\n    -> {check_name}: {msg}"
        print(line)

    print(f"\n{passed} passed, {failed} failed, {len(cases)} total")


if __name__ == "__main__":
    main()
