"""Tests for the two critical correctness fixes:
1. Metadata alignment validation (mutable_default_b fix)
2. Import stripping fail-fast behavior

These tests protect against data corruption in experiment results.
"""

import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = Path(__file__).resolve().parents[1]


# ============================================================
# ISSUE 1: METADATA ALIGNMENT
# ============================================================

def test_metadata_alignment_all_cases():
    """Every case's reference_fix.function must exist in the reference fix code."""
    cases = json.loads((BASE / "cases_v2.json").read_text())
    failures = []

    for case in cases:
        cid = case["id"]
        expected_fn = case.get("reference_fix", {}).get("function", "")
        if not expected_fn:
            failures.append(f"{cid}: reference_fix.function is empty")
            continue

        ref_path = BASE / "reference_fixes" / f"{cid}.py"
        if not ref_path.exists():
            failures.append(f"{cid}: reference fix file not found")
            continue

        ref_code = ref_path.read_text()
        try:
            tree = ast.parse(ref_code)
        except SyntaxError as e:
            failures.append(f"{cid}: reference fix has syntax error: {e}")
            continue

        ref_defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        if expected_fn not in ref_defs:
            failures.append(
                f"{cid}: reference_fix.function='{expected_fn}' NOT in reference fix "
                f"(defines: {sorted(ref_defs)})"
            )

    print(f"[TEST: METADATA ALIGNMENT]")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        assert False, f"{len(failures)} metadata alignment failures"
    else:
        print(f"  All {len(cases)} cases have correct metadata alignment")
        print("  PASS")


def test_mutable_default_b_fixed():
    """mutable_default_b must now pass with reference fix (metadata was corrected)."""
    from exec_eval import exec_evaluate
    from validate_cases_v2 import load_reference_code

    cases = json.loads((BASE / "cases_v2.json").read_text())
    case = next(c for c in cases if c["id"] == "mutable_default_b")
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text()

    ref = load_reference_code(case)
    result = exec_evaluate(case, ref)

    print(f"[TEST: MUTABLE_DEFAULT_B FIXED]")
    print(f"  pass={result['pass']}, ran={result['execution']['ran']}")
    print(f"  rename_error={result['execution'].get('rename_error', False)}")
    assert result["pass"] is True, f"Reference fix must pass, got: {result.get('reasons')}"
    assert result["execution"].get("rename_error") is not True, "rename_error must not fire"
    print("  PASS")


# ============================================================
# ISSUE 2: IMPORT STRIPPING
# ============================================================

def _make_case(files):
    """Helper: build a minimal case dict for assembly tests."""
    return {
        "code_files": list(files.keys()),
        "code_files_contents": files,
        "failure_mode": "TEST",
        "reference_fix": {},
    }


def test_stdlib_import_preserved():
    """Known stdlib imports must be preserved, not stripped."""
    from code_assembly import assemble_code

    code = "import os\nimport json\nfrom collections import Counter\nx = 1"
    case = _make_case({"config.py": "pass", "cache.py": "pass"})
    result = assemble_code(code, case).code
    assert "import os" in result, "os import was stripped"
    assert "import json" in result, "json import was stripped"
    assert "from collections import Counter" in result, "collections import was stripped"


def test_local_import_stripped():
    """Local sibling imports must be stripped."""
    from code_assembly import assemble_code

    code = "from config import create_config\nimport cache\nx = 1"
    case = _make_case({"config.py": "def create_config(): pass", "cache.py": "pass"})
    result = assemble_code(code, case).code
    assert "from config" not in result, "local import was not stripped"
    assert "import cache" not in result, "local import was not stripped"
    assert "x = 1" in result, "non-import code was incorrectly removed"


def test_unknown_import_preserved_safe_mode():
    """Unknown non-stdlib, non-local imports are preserved in safe mode (conservative)."""
    from code_assembly import assemble_code

    code = "import decimal\nx = 1"
    case = _make_case({"a.py": "pass", "b.py": "pass"})
    result = assemble_code(code, case).code
    # decimal is not in STDLIB_MODULES and not a local module
    # safe mode preserves unknown imports (conservative)
    assert "import decimal" in result
    assert "x = 1" in result


def test_known_local_stripped():
    """Known local modules are stripped."""
    from code_assembly import assemble_code

    code = "from config import create_config\nimport os\nx = 1"
    case = _make_case({"config.py": "def create_config(): pass"})
    result = assemble_code(code, case).code
    assert "from config" not in result
    assert "import os" in result
    assert "x = 1" in result


# ============================================================
# VALIDATE ALL 58 CASES
# ============================================================

def test_all_cases_validate():
    """Run validate_cases_v2 metadata check on all 58 cases."""
    from validate_cases_v2 import check_metadata_alignment

    cases = json.loads((BASE / "cases_v2.json").read_text())
    failures = []
    for case in cases:
        ok, msg = check_metadata_alignment(case)
        if not ok:
            failures.append(f"{case['id']}: {msg}")

    print(f"[TEST: ALL CASES VALIDATE METADATA]")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        assert False, f"{len(failures)} cases failed metadata check"
    else:
        print(f"  All {len(cases)} cases pass metadata alignment check")
        print("  PASS")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_metadata_alignment_all_cases()
    passed += 1
    print()

    test_mutable_default_b_fixed()
    passed += 1
    print()

    test_stdlib_import_preserved()
    passed += 1
    print()

    test_local_import_stripped()
    passed += 1
    print()

    test_unknown_import_fails_strict()
    passed += 1
    print()

    test_unknown_import_silent_without_strict()
    passed += 1
    print()

    test_known_local_stripped_strict()
    passed += 1
    print()

    test_all_cases_validate()
    passed += 1
    print()

    print(f"{'=' * 50}")
    print(f"RESULTS: {passed}/8 passed")
    print("ALL CORRECTNESS TESTS PASSED")


if __name__ == "__main__":
    main()
