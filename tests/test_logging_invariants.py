"""Tests for logging/instrumentation correctness.

Verifies that execution metadata (ran, total_tests, extracted_code) is
internally consistent and grounded in actual execution, not assumed.
"""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from exec_eval import exec_evaluate, _exec_info
from validate_cases_v2 import load_reference_code, load_case_code


def _load_case(case_id):
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == case_id)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


# ============================================================
# TEST 1 — Early return paths must have ran=False, total_tests=0
# ============================================================

class TestEarlyReturnLogging:

    def test_rename_error_has_zero_tests(self):
        """mutable_default_b triggers rename_error → ran=False, total_tests=0."""
        case = _load_case("mutable_default_b")
        # Use reference fix which triggers rename (defines process_batch, not enqueue)
        ref = load_reference_code(case)
        result = exec_evaluate(case, ref)
        ex = result["execution"]
        assert ex["ran"] is False, f"Expected ran=False, got {ex['ran']}"
        assert ex["total_tests"] == 0, f"Expected total_tests=0, got {ex['total_tests']}"
        assert ex["passed_tests"] == 0

    def test_empty_code_has_zero_tests(self):
        """Empty code → ran=False, total_tests=0."""
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "")
        ex = result["execution"]
        assert ex["ran"] is False
        assert ex["total_tests"] == 0

    def test_short_code_has_zero_tests(self):
        """Code < 10 chars → ran=False, total_tests=0."""
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "x = 1")
        ex = result["execution"]
        assert ex["ran"] is False
        assert ex["total_tests"] == 0

    def test_syntax_error_has_zero_tests(self):
        """Syntax error in code → ran=False, total_tests=0."""
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "def f(:\n    pass\n" * 5)
        ex = result["execution"]
        assert ex["ran"] is False
        assert ex["total_tests"] == 0


# ============================================================
# TEST 2 — Successful execution must have ran=True, total_tests>0
# ============================================================

class TestSuccessfulExecutionLogging:

    def test_passing_case_has_tests_run(self):
        """alias_config_a with reference fix → ran=True, total_tests=2."""
        case = _load_case("alias_config_a")
        ref = load_reference_code(case)
        result = exec_evaluate(case, ref)
        ex = result["execution"]
        assert ex["ran"] is True, f"Expected ran=True, got {ex['ran']}"
        assert ex["total_tests"] == 2, f"Expected total_tests=2, got {ex['total_tests']}"
        assert ex["passed_tests"] == 2

    def test_failing_case_still_has_tests_run(self):
        """Buggy code that runs but fails → ran=True, total_tests>=1."""
        case = _load_case("alias_config_a")
        buggy = load_case_code(case)
        result = exec_evaluate(case, buggy)
        ex = result["execution"]
        assert ex["ran"] is True, f"Expected ran=True, got {ex['ran']}"
        assert ex["total_tests"] >= 1, f"Expected total_tests>=1, got {ex['total_tests']}"


# ============================================================
# TEST 3 — Invariant: NOT (ran=False AND total_tests>0)
# ============================================================

class TestLoggingInvariant:

    def test_exec_info_invariant_rejects_impossible_state(self):
        """_exec_info must reject ran=False with total_tests>0."""
        with pytest.raises(AssertionError, match="LOGGING BUG"):
            _exec_info(ran=False, total_tests=2)

    def test_exec_info_allows_ran_true_with_tests(self):
        """ran=True with total_tests>0 is valid."""
        info = _exec_info(ran=True, total_tests=2, passed_tests=1, invariant_pass=False)
        assert info["ran"] is True
        assert info["total_tests"] == 2

    def test_exec_info_allows_ran_false_with_zero_tests(self):
        """ran=False with total_tests=0 is valid."""
        info = _exec_info(ran=False, total_tests=0)
        assert info["ran"] is False
        assert info["total_tests"] == 0


# ============================================================
# TEST 4 — Generated code is always present
# ============================================================

class TestExtractedCodePresent:

    def test_passing_case_has_extracted_code(self):
        case = _load_case("alias_config_a")
        ref = load_reference_code(case)
        result = exec_evaluate(case, ref)
        code = result.get("_extracted_code", "")
        assert code and code.strip(), f"Expected non-empty extracted code, got {code!r}"

    def test_empty_input_has_extraction_failed_marker(self):
        case = _load_case("alias_config_a")
        result = exec_evaluate(case, "")
        code = result.get("_extracted_code", "")
        assert code == "<EXTRACTION FAILED>"

    def test_rename_error_has_extracted_code(self):
        case = _load_case("mutable_default_b")
        ref = load_reference_code(case)
        result = exec_evaluate(case, ref)
        code = result.get("_extracted_code", "")
        assert code and code.strip(), f"Expected non-empty extracted code, got {code!r}"
        assert code != "<EXTRACTION FAILED>"
