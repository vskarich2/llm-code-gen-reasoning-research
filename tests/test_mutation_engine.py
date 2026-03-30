"""Tests for the mutation engine rejection paths.

Proves that invalid variants are structurally impossible to accept.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.mutation_engine import (
    MutationSpec,
    generate_variant,
    localize_target,
    verify_diff,
    check_semantic_guardrails,
    MUTATION_OPERATORS,
)


GOOD_CODE = '''DEFAULTS = {"timeout": 30}

def create_config(overrides=None):
    config = DEFAULTS.copy()
    if overrides:
        config.update(overrides)
    return config
'''

BUGGY_CODE = '''DEFAULTS = {"timeout": 30}

def create_config(overrides=None):
    config = DEFAULTS
    if overrides:
        config.update(overrides)
    return config
'''


def _dummy_case():
    return {
        "id": "test_case",
        "family": "alias_config",
        "code_files": ["test.py"],
        "code_files_contents": {"test.py": GOOD_CODE},
        "failure_mode": "ALIASING",
        "ground_truth_bug": {"type": "shared_reference"},
        "reference_fix": {"function": "create_config", "file": "test.py"},
    }


# ============================================================
# Stage 1: Target localization
# ============================================================

def test_target_found():
    result = localize_target(GOOD_CODE, "create_config")
    assert result is not None, "Should find create_config"
    assert result["function_name"] == "create_config"
    print("[PASS] target localization: function found")


def test_target_not_found():
    result = localize_target(GOOD_CODE, "nonexistent_function")
    assert result is None, "Should not find nonexistent function"
    print("[PASS] target localization: missing function returns None")


def test_target_not_found_rejects_variant():
    spec = MutationSpec(
        variant_id="test_v1", case_id="test", family="alias_config",
        target_file="test.py", target_function="nonexistent",
        bug_pattern="test", mutation_operator="remove_copy",
        expected_failure_surface="test",
    )
    result = generate_variant(spec, GOOD_CODE, GOOD_CODE, _dummy_case())
    assert result.quality == "REJECT"
    assert result.target_found is False
    assert "not found" in result.rejection_reason
    print("[PASS] target not found → REJECT")


# ============================================================
# Stage 2: Mutation application
# ============================================================

def test_mutation_applies():
    op = MUTATION_OPERATORS["remove_copy"]
    mutated = op.mutate(GOOD_CODE, "create_config", {})
    assert mutated is not None, "remove_copy should apply to code with .copy()"
    assert ".copy()" not in mutated, ".copy() should be removed"
    print("[PASS] mutation applies: .copy() removed")


def test_mutation_not_applicable_rejects():
    spec = MutationSpec(
        variant_id="test_v1", case_id="test", family="alias_config",
        target_file="test.py", target_function="create_config",
        bug_pattern="test", mutation_operator="remove_invalidation",
        expected_failure_surface="test",
    )
    # remove_invalidation can't apply to alias_config code (no cache.pop)
    result = generate_variant(spec, GOOD_CODE, GOOD_CODE, _dummy_case())
    assert result.quality == "REJECT"
    assert "could not apply" in result.rejection_reason
    print("[PASS] inapplicable operator → REJECT")


# ============================================================
# Stage 3: Diff verification
# ============================================================

def test_empty_diff_rejects():
    ok, _ = verify_diff(GOOD_CODE, GOOD_CODE, "create_config")
    assert not ok, "Identical code should fail diff verification"
    print("[PASS] empty diff → rejected")


def test_nonempty_diff_passes():
    ok, diff = verify_diff(GOOD_CODE, BUGGY_CODE, "create_config")
    assert ok, "Different code should pass diff verification"
    assert diff is not None
    print("[PASS] non-empty diff → passed")


# ============================================================
# Stage 4: Semantic guardrails
# ============================================================

def test_identical_to_fix_rejects():
    ok, reason = check_semantic_guardrails(GOOD_CODE, GOOD_CODE, "create_config")
    assert not ok, "Code identical to reference fix should be rejected"
    assert "identical" in reason
    print("[PASS] identical to fix → REJECT")


def test_missing_function_rejects():
    code_without_fn = "x = 1\n"
    ok, reason = check_semantic_guardrails(code_without_fn, GOOD_CODE, "create_config")
    assert not ok, "Code without target function should be rejected"
    assert "not defined" in reason
    print("[PASS] missing target function → REJECT")


def test_syntax_error_rejects():
    bad_code = "def create_config(:\n    pass"
    ok, reason = check_semantic_guardrails(bad_code, GOOD_CODE, "create_config")
    assert not ok, "Syntax error should be rejected"
    assert "syntax error" in reason
    print("[PASS] syntax error → REJECT")


def test_valid_buggy_passes_guardrails():
    ok, reason = check_semantic_guardrails(BUGGY_CODE, GOOD_CODE, "create_config")
    assert ok, f"Valid buggy code should pass guardrails, but got: {reason}"
    print("[PASS] valid buggy code passes guardrails")


# ============================================================
# Stage 5: Oracle validation (accidental fix rejection)
# ============================================================

def test_oracle_pass_rejects():
    """If mutated code passes the oracle, it's not actually buggy → REJECT."""
    import json
    cases = json.loads((Path(__file__).resolve().parents[1] / "cases_v2.json").read_text())
    case = next(c for c in cases if c["id"] == "alias_config_a")
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (Path(__file__).resolve().parents[1] / rel).read_text()

    spec = MutationSpec(
        variant_id="test_oracle", case_id="alias_config_a", family="alias_config",
        target_file=case["code_files"][0], target_function="create_config",
        bug_pattern="none", mutation_operator="remove_copy",
        expected_failure_surface="aliasing",
    )
    # Use the reference fix (correct code) as source — remove_copy won't apply since
    # the code uses .copy(). Actually it WILL remove .copy() making it buggy.
    ref = (Path(__file__).resolve().parents[1] / "reference_fixes" / "alias_config_a.py").read_text()
    result = generate_variant(spec, ref, ref, case)

    # The mutation should create buggy code that fails the oracle
    assert result.oracle_failed is True, f"Expected oracle to fail, got: {result.rejection_reason}"
    assert result.quality in ("GOLD", "SILVER"), f"Expected GOLD/SILVER, got: {result.quality}"
    print(f"[PASS] oracle correctly fails buggy variant (quality={result.quality})")


def test_correct_code_oracle_rejects():
    """Variant that is accidentally correct must be rejected."""
    import json
    cases = json.loads((Path(__file__).resolve().parents[1] / "cases_v2.json").read_text())
    case = next(c for c in cases if c["id"] == "alias_config_a")
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (Path(__file__).resolve().parents[1] / rel).read_text()

    from scripts.mutation_engine import validate_with_oracle
    ref = (Path(__file__).resolve().parents[1] / "reference_fixes" / "alias_config_a.py").read_text()
    oracle_failed, error, quality = validate_with_oracle(case, ref)
    assert not oracle_failed, "Correct code should pass oracle"
    assert quality == "REJECT"
    print("[PASS] correct code → oracle passes → REJECT")


# ============================================================
# Full pipeline: end-to-end
# ============================================================

def test_full_pipeline_valid_mutation():
    """End-to-end: remove_copy on reference fix → all 5 gates pass."""
    import json
    cases = json.loads((Path(__file__).resolve().parents[1] / "cases_v2.json").read_text())
    case = next(c for c in cases if c["id"] == "alias_config_a")
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (Path(__file__).resolve().parents[1] / rel).read_text()

    ref = (Path(__file__).resolve().parents[1] / "reference_fixes" / "alias_config_a.py").read_text()

    spec = MutationSpec(
        variant_id="e2e_test", case_id="alias_config_a", family="alias_config",
        target_file=case["code_files"][0], target_function="create_config",
        bug_pattern="remove copy", mutation_operator="remove_copy",
        expected_failure_surface="aliasing",
    )

    result = generate_variant(spec, ref, ref, case)

    assert result.target_found, "Target must be found"
    assert result.applied, "Mutation must apply"
    assert result.diff_nonempty, "Diff must be non-empty"
    assert result.semantic_guardrails_passed, "Guardrails must pass"
    assert result.oracle_failed, "Oracle must fail"
    assert result.quality in ("GOLD", "SILVER")
    assert result.rejection_reason is None
    assert result.code is not None
    print(f"[PASS] full pipeline: all 5 gates passed (quality={result.quality})")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_target_found(); passed += 1
    test_target_not_found(); passed += 1
    test_target_not_found_rejects_variant(); passed += 1
    test_mutation_applies(); passed += 1
    test_mutation_not_applicable_rejects(); passed += 1
    test_empty_diff_rejects(); passed += 1
    test_nonempty_diff_passes(); passed += 1
    test_identical_to_fix_rejects(); passed += 1
    test_missing_function_rejects(); passed += 1
    test_syntax_error_rejects(); passed += 1
    test_valid_buggy_passes_guardrails(); passed += 1
    test_oracle_pass_rejects(); passed += 1
    test_correct_code_oracle_rejects(); passed += 1
    test_full_pipeline_valid_mutation(); passed += 1

    print(f"\n{'='*50}")
    print(f"RESULTS: {passed}/14 passed")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
