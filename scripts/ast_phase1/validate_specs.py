"""Validate AST checkers against reference fixes and buggy code."""

import ast
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from checkers import CASE_RULES, find_function
from checker_fixes import CASE_RULES_OVERRIDES, MODULE_LEVEL_CASES

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CASES_PATH = os.path.join(PROJECT_ROOT, "case_data", "cases_v2.json")
REF_FIXES_DIR = os.path.join(PROJECT_ROOT, "case_data", "reference_fixes")


def load_cases():
    with open(CASES_PATH) as f:
        return {c["id"]: c for c in json.load(f)}


def read_ref_fix(case_id):
    path = os.path.join(REF_FIXES_DIR, f"{case_id}.py")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def read_buggy_code(case):
    ref_file = case["reference_fix"]["file"]
    path = os.path.join(PROJECT_ROOT, ref_file)
    if not os.path.exists(path):
        # Try with case_data/ prefix (repo was restructured)
        path = os.path.join(PROJECT_ROOT, "case_data", ref_file)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


def get_rules(case_id):
    """Get the CLAUDE_RULES for a case, applying overrides."""
    if case_id in CASE_RULES_OVERRIDES:
        return CASE_RULES_OVERRIDES[case_id], False
    if case_id in MODULE_LEVEL_CASES:
        return MODULE_LEVEL_CASES[case_id], True  # module-level check
    if case_id in CASE_RULES:
        return CASE_RULES[case_id], False
    return None, False


def run_checker(code, case_id, rules, is_module_level):
    """Run strict and relaxed checkers."""
    func_name, strict_fn, relaxed_fn, anti_fn, partial_fn = rules

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, False, f"SyntaxError: {e}"

    if is_module_level:
        # Module-level check: pass the tree directly
        strict_ok = strict_fn(tree)
        relaxed_ok = relaxed_fn(tree)
        anti_found = anti_fn(tree) if anti_fn else False
    else:
        func_node = find_function(tree, func_name)
        if func_node is None:
            return False, False, f"function '{func_name}' not found"
        strict_ok = strict_fn(func_node)
        relaxed_ok = relaxed_fn(func_node)
        anti_found = anti_fn(func_node) if anti_fn else False

    strict_pass = strict_ok and not anti_found
    relaxed_pass = relaxed_ok and not anti_found
    return strict_pass, relaxed_pass, f"strict={strict_ok}, relaxed={relaxed_ok}, anti={anti_found}"


def main():
    cases = load_cases()
    passed = 0
    failed = 0
    skipped = 0
    errors = []

    all_case_ids = set(CASE_RULES.keys()) | set(CASE_RULES_OVERRIDES.keys()) | set(MODULE_LEVEL_CASES.keys())

    for case_id in sorted(all_case_ids):
        case = cases.get(case_id)
        if case is None:
            skipped += 1
            continue

        rules, is_module = get_rules(case_id)
        if rules is None:
            skipped += 1
            continue

        ref_code = read_ref_fix(case_id)
        if ref_code is None:
            print(f"  SKIP {case_id}: no reference fix file")
            skipped += 1
            continue

        # Validate on reference fix (MUST PASS)
        ref_strict, ref_relaxed, ref_reason = run_checker(ref_code, case_id, rules, is_module)
        if not ref_relaxed:
            print(f"  FAIL {case_id} ref RELAXED: {ref_reason}")
            errors.append(f"{case_id} ref relaxed: {ref_reason}")
            failed += 1
            continue

        # Validate on buggy code (MUST FAIL relaxed)
        buggy_code = read_buggy_code(case)
        if buggy_code is None:
            print(f"  SKIP {case_id}: no buggy code")
            skipped += 1
            continue

        buggy_strict, buggy_relaxed, buggy_reason = run_checker(buggy_code, case_id, rules, is_module)
        if buggy_relaxed:
            print(f"  FAIL {case_id} buggy RELAXED: should have FAILED but PASSED ({buggy_reason})")
            errors.append(f"{case_id} buggy relaxed: {buggy_reason}")
            failed += 1
            continue

        s_tag = "S=T" if ref_strict else "S=F"
        print(f"  OK   {case_id}: ref({s_tag},R=T) buggy(R=F)")
        passed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} OK, {failed} FAILED, {skipped} SKIPPED")
    if errors:
        print(f"\nErrors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nAll validations passed.")


if __name__ == "__main__":
    main()
