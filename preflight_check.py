"""Pre-flight check: verify every case has a working test BEFORE running an ablation.

Run this before any experiment:
    .venv/bin/python preflight_check.py
    .venv/bin/python preflight_check.py --cases cases_v2.json

Exit code 0 = all cases ready. Exit code 1 = failures found, DO NOT run ablation.
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from exec_eval import _CASE_TESTS, _load_v2_test, load_module_from_code

BASE = Path(__file__).parent

_STDLIB = {
    "os",
    "sys",
    "json",
    "re",
    "math",
    "copy",
    "collections",
    "functools",
    "itertools",
    "typing",
    "pathlib",
    "datetime",
    "abc",
    "dataclasses",
    "enum",
    "logging",
    "hashlib",
    "random",
    "io",
    "string",
    "textwrap",
}


def _strip_local_imports(code: str) -> str:
    lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("from ") and " import " in s:
            mod = s.split()[1].split(".")[0]
            if mod not in _STDLIB:
                continue
        lines.append(line)
    return "\n".join(lines)


def _load_buggy_code(case: dict) -> str:
    parts = []
    for rel in case["code_files"]:
        path = BASE / rel
        if not path.exists():
            raise FileNotFoundError(f"Code file missing: {rel}")
        parts.append(path.read_text(encoding="utf-8"))
    return _strip_local_imports("\n\n".join(parts))


def check_case(case: dict) -> dict:
    """Run all pre-flight checks for a single case.

    Returns dict with:
        ok: bool
        checks: dict of check_name -> (passed, message)
    """
    cid = case["id"]
    checks = {}

    # CHECK 1: Test function resolves
    test_fn = _CASE_TESTS.get(cid) or _load_v2_test(case)
    if test_fn is None:
        checks["test_resolves"] = (
            False,
            "NO TEST FOUND — _CASE_TESTS and _load_v2_test both returned None",
        )
        return {"ok": False, "checks": checks}
    checks["test_resolves"] = (True, f"{test_fn.__name__} from {test_fn.__module__}")

    # CHECK 2: Code files exist
    missing = [f for f in case["code_files"] if not (BASE / f).exists()]
    if missing:
        checks["code_exists"] = (False, f"Missing: {missing}")
        return {"ok": False, "checks": checks}
    checks["code_exists"] = (True, f"{len(case['code_files'])} files")

    # CHECK 3: Buggy code loads
    try:
        code = _load_buggy_code(case)
        mod = load_module_from_code(code, f"preflight_{cid}")
    except Exception as e:
        checks["code_loads"] = (False, str(e))
        return {"ok": False, "checks": checks}
    checks["code_loads"] = (True, "module loaded")

    # CHECK 4: Test RUNS on buggy code (doesn't crash)
    try:
        passed, reasons = test_fn(mod)
    except Exception as e:
        checks["test_runs"] = (False, f"Test crashed: {e}")
        return {"ok": False, "checks": checks}
    checks["test_runs"] = (True, "test executed without crash")

    # CHECK 5: Test FAILS on buggy code (bug is real)
    if passed:
        checks["test_detects_bug"] = (
            False,
            f"Test PASSES on buggy code — bug not detected. Reasons: {reasons}",
        )
        return {"ok": False, "checks": checks}
    checks["test_detects_bug"] = (True, f"test correctly fails: {reasons[0][:80]}")

    # CHECK 6: Reference fix exists
    ref_path = BASE / "reference_fixes" / f"{cid}.py"
    if not ref_path.exists():
        checks["ref_fix_exists"] = (False, f"reference_fixes/{cid}.py not found")
        # Not a blocker — some cases may not have ref fixes yet
        return {"ok": True, "checks": checks}
    checks["ref_fix_exists"] = (True, str(ref_path))

    # CHECK 7: Test PASSES on reference fix
    try:
        ref_code = ref_path.read_text(encoding="utf-8")
        # For multi-file cases, merge ref fix with non-bug files
        bug_file = case.get("reference_fix", {}).get("file", "")
        other_parts = []
        for rel in case["code_files"]:
            if rel != bug_file:
                path = BASE / rel
                if path.exists():
                    other_parts.append(path.read_text(encoding="utf-8"))
        if other_parts:
            full_ref = _strip_local_imports("\n\n".join(other_parts) + "\n\n" + ref_code)
        else:
            full_ref = _strip_local_imports(ref_code)

        ref_mod = load_module_from_code(full_ref, f"preflight_ref_{cid}")
        ref_passed, ref_reasons = test_fn(ref_mod)
        if not ref_passed:
            checks["ref_fix_passes"] = (False, f"Test FAILS on reference fix: {ref_reasons}")
            return {"ok": False, "checks": checks}
        checks["ref_fix_passes"] = (True, "reference fix passes test")
    except Exception as e:
        checks["ref_fix_passes"] = (False, f"Reference fix error: {e}")
        return {"ok": False, "checks": checks}

    return {"ok": True, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="Pre-flight check for ablation runs")
    parser.add_argument("--cases", default="cases_v2.json")
    parser.add_argument("--case", default=None, help="Check a single case")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cases = json.loads((BASE / args.cases).read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"Case {args.case} not found")
            sys.exit(1)

    passed = 0
    failed = 0
    for case in cases:
        result = check_case(case)
        if result["ok"]:
            passed += 1
            if args.verbose:
                print(f"  OK  {case['id']}")
        else:
            failed += 1
            print(f"  FAIL {case['id']}")
            for check, (ok, msg) in result["checks"].items():
                if not ok:
                    print(f"       {check}: {msg}")

    print(f"\n{passed} passed, {failed} failed, {len(cases)} total")

    if failed > 0:
        print("\nABLATION BLOCKED — fix failures before running")
        sys.exit(1)
    else:
        print("\nALL CHECKS PASS — safe to run ablation")
        sys.exit(0)


if __name__ == "__main__":
    main()
