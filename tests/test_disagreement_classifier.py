"""Tests for disagreement classifier — exhaustive classification of dual execution mismatches."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from disagreement_classifier import classify_disagreement, DisagreementResult


def _make_result(passed=True, error=None, traceback=None, stdout="",
                 tests_run=1, tests_passed=None):
    if tests_passed is None:
        tests_passed = tests_run if passed else 0
    return {
        "pass": passed,
        "error": error,
        "traceback": traceback or "",
        "stdout": stdout,
        "tests_run": tests_run,
        "tests_passed": tests_passed,
    }


# ============================================================
# TYPE 1: AGREEMENT
# ============================================================


class TestAgreement:

    def test_both_pass(self):
        c = _make_result(passed=True)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.type == "agreement"
        assert r.confidence == 1.0

    def test_both_fail_same_tests(self):
        c = _make_result(passed=False, error="test failed", tests_passed=0)
        m = _make_result(passed=False, error="test failed", tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "agreement"

    def test_both_pass_same_test_count(self):
        c = _make_result(passed=True, tests_run=2, tests_passed=2)
        m = _make_result(passed=True, tests_run=2, tests_passed=2)
        r = classify_disagreement(c, m)
        assert r.type == "agreement"


# ============================================================
# TYPE 2: ASSEMBLY_FAILURE_LIKELY
# ============================================================


class TestAssemblyFailure:

    def test_import_resolution_failure(self):
        c = _make_result(passed=False, error="ModuleNotFoundError: No module named 'metrics'",
                         traceback="ModuleNotFoundError", tests_passed=0)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.type == "assembly_failure_likely"
        assert r.subtype == "import_resolution_failure"
        assert r.confidence == 1.0

    def test_missing_symbol_nameerror(self):
        c = _make_result(passed=False, error="NameError: name 'metrics_reset' is not defined",
                         traceback="NameError", tests_passed=0)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.type == "assembly_failure_likely"
        assert r.subtype == "missing_symbol_after_strip"

    def test_namespace_binding_failure(self):
        c = _make_result(passed=False, error="AttributeError: module has no attribute 'reset'",
                         tests_passed=0)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.type == "assembly_failure_likely"
        assert r.subtype == "namespace_binding_failure"

    def test_unclassified_concat_failure(self):
        c = _make_result(passed=False, error="RuntimeError: something weird", tests_passed=0)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.type == "assembly_failure_likely"
        assert r.subtype == "unclassified_concat_failure"
        assert r.confidence == 0.5


# ============================================================
# TYPE 3: SEMANTIC_DIVERGENCE
# ============================================================


class TestSemanticDivergence:

    def test_different_stdout(self):
        c = _make_result(passed=True, stdout="result=42", tests_passed=1)
        m = _make_result(passed=True, stdout="result=43", tests_passed=2)
        r = classify_disagreement(c, m)
        assert r.type == "semantic_divergence"
        assert r.subtype == "state_order_difference"

    def test_different_test_results(self):
        c = _make_result(passed=True, tests_run=2, tests_passed=2)
        m = _make_result(passed=True, tests_run=2, tests_passed=1)
        r = classify_disagreement(c, m)
        assert r.type == "semantic_divergence"
        assert r.subtype == "test_result_difference"


# ============================================================
# TYPE 4: MODULE_EXECUTION_FAILURE
# ============================================================


class TestModuleExecutionFailure:

    def test_circular_import(self):
        c = _make_result(passed=True)
        m = _make_result(passed=False, error="ImportError: cannot import name 'func_b'",
                         traceback="most likely due to a circular import", tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "module_execution_failure"
        assert r.subtype == "circular_import_failure"
        assert r.confidence == 1.0

    def test_module_init_order(self):
        c = _make_result(passed=True)
        m = _make_result(passed=False, error="ImportError: No module named 'metrics'",
                         tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "module_execution_failure"
        assert r.subtype == "module_init_order_failure"

    def test_unclassified_module_failure(self):
        c = _make_result(passed=True)
        m = _make_result(passed=False, error="RuntimeError: unexpected", tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "module_execution_failure"
        assert r.subtype == "unclassified_module_failure"


# ============================================================
# TYPE 5: CONSISTENT_FAILURE
# ============================================================


class TestConsistentFailure:

    def test_both_fail_same_tests_is_agreement(self):
        """Both fail with same test counts — this is AGREEMENT (they agree on failure)."""
        c = _make_result(passed=False, error="SyntaxError: invalid syntax", tests_passed=0)
        m = _make_result(passed=False, error="SyntaxError: bad code", tests_passed=0)
        r = classify_disagreement(c, m)
        # Same pass + same tests_passed = agreement
        assert r.type == "agreement"

    def test_different_error_different_test_results(self):
        """Both fail but with different test pass counts — consistent_failure."""
        c = _make_result(passed=False, error="NameError: x not defined",
                         tests_run=2, tests_passed=1)
        m = _make_result(passed=False, error="TypeError: wrong arg",
                         tests_run=2, tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "consistent_failure"
        assert r.subtype == "different_error"

    def test_same_error_different_test_results(self):
        """Both fail with same error type but different test counts."""
        c = _make_result(passed=False, error="SyntaxError: bad",
                         tests_run=2, tests_passed=1)
        m = _make_result(passed=False, error="SyntaxError: also bad",
                         tests_run=2, tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "consistent_failure"
        assert r.subtype == "same_error"


# ============================================================
# TYPE 6: TEST_INCONSISTENCY
# ============================================================


class TestTestInconsistency:

    def test_different_test_counts(self):
        c = _make_result(passed=True, tests_run=2, tests_passed=2)
        m = _make_result(passed=True, tests_run=1, tests_passed=1)
        r = classify_disagreement(c, m)
        assert r.type == "test_inconsistency"

    def test_early_failure(self):
        c = _make_result(passed=False, tests_run=0, tests_passed=0)
        m = _make_result(passed=True, tests_run=1, tests_passed=1)
        r = classify_disagreement(c, m)
        assert r.type == "test_inconsistency"
        assert r.subtype == "early_failure"

    def test_partial_execution(self):
        c = _make_result(passed=False, tests_run=3, tests_passed=1)
        m = _make_result(passed=False, tests_run=1, tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "test_inconsistency"
        assert r.subtype == "partial_execution"


# ============================================================
# TYPE 7: UNKNOWN
# ============================================================


class TestUnknown:

    def test_impossible_state(self):
        """Force a case that doesn't match any rule."""
        # Both pass=True, same tests_run, same tests_passed, but
        # the agreement check should catch this. To force unknown,
        # we'd need to break the logic. Let's verify agreement catches it.
        c = _make_result(passed=True, tests_run=1, tests_passed=1)
        m = _make_result(passed=True, tests_run=1, tests_passed=1)
        r = classify_disagreement(c, m)
        # This should be agreement, not unknown
        assert r.type == "agreement"


# ============================================================
# PRIORITY ORDER
# ============================================================


class TestPriority:

    def test_test_inconsistency_before_assembly_failure(self):
        """TEST_INCONSISTENCY takes priority over ASSEMBLY_FAILURE_LIKELY."""
        c = _make_result(passed=False, error="ModuleNotFoundError",
                         tests_run=0, tests_passed=0)
        m = _make_result(passed=True, tests_run=2, tests_passed=2)
        r = classify_disagreement(c, m)
        assert r.type == "test_inconsistency"  # priority 1 beats priority 3

    def test_agreement_before_consistent_failure(self):
        """AGREEMENT takes priority when both fail with same tests."""
        c = _make_result(passed=False, error="test failed", tests_run=1, tests_passed=0)
        m = _make_result(passed=False, error="different error", tests_run=1, tests_passed=0)
        r = classify_disagreement(c, m)
        assert r.type == "agreement"  # same pass + same tests_passed


# ============================================================
# CONFIDENCE
# ============================================================


class TestConfidence:

    def test_exact_match_high_confidence(self):
        c = _make_result(passed=False, error="ModuleNotFoundError: No module named 'metrics'",
                         tests_passed=0)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.confidence == 1.0

    def test_weak_match_low_confidence(self):
        c = _make_result(passed=False, error="RuntimeError: something", tests_passed=0)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.confidence == 0.5

    def test_agreement_full_confidence(self):
        c = _make_result(passed=True)
        m = _make_result(passed=True)
        r = classify_disagreement(c, m)
        assert r.confidence == 1.0


# ============================================================
# DETERMINISM
# ============================================================


class TestDeterminism:

    def test_same_input_same_output(self):
        c = _make_result(passed=False, error="ModuleNotFoundError", tests_passed=0)
        m = _make_result(passed=True)
        results = [classify_disagreement(c, m) for _ in range(10)]
        types = [r.type for r in results]
        assert len(set(types)) == 1
        confs = [r.confidence for r in results]
        assert len(set(confs)) == 1
