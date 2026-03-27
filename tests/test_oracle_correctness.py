"""L-1: Test Oracle Correctness Validation.

Validates that the test functions themselves are correct:
- Interface compatible with exec_evaluate (takes single mod, not mods dict)
- Buggy code fails (oracle can detect bugs)
- Reference fixes pass (oracle accepts correct code)
- Adversarial perturbations are caught (oracle has failure sensitivity)
- No zero-sensitivity cases (oracle distinguishes correct from incorrect)
"""

import json
import re
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from exec_eval import exec_evaluate, load_module_from_code, _load_v2_test, _assemble_program
from validate_cases_v2 import load_case_code, load_reference_code, load_test_func

# ============================================================
# HELPERS
# ============================================================


def _all_cases():
    cases_path = BASE / "cases_v2.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    for case in cases:
        case["code_files_contents"] = {}
        for rel in case["code_files"]:
            case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return cases


def _case_ids():
    return [c["id"] for c in _all_cases()]


ALL_CASES = _all_cases()
CASE_IDS = [c["id"] for c in ALL_CASES]


# ============================================================
# ORACLE INTERFACE COMPATIBILITY
# ============================================================


class TestOracleInterface:
    """Every test function must accept a single module (not a mods dict)."""

    @pytest.mark.parametrize("case_id", CASE_IDS)
    def test_oracle_interface_compatible(self, case_id):
        """Test function accepts single mod and returns (bool, list[str])."""
        case = next(c for c in ALL_CASES if c["id"] == case_id)
        test_fn = load_test_func(case)
        assert test_fn is not None, f"No test function for {case_id}"

        # Load buggy code as module (same path as exec_evaluate)
        code = load_case_code(case)
        mod = load_module_from_code(code, f"iface_check_{case_id}")

        # Call must not crash — TypeError means mods dict interface
        result = test_fn(mod)
        assert isinstance(result, tuple), f"test_fn returned {type(result)}, expected tuple"
        assert len(result) == 2, f"test_fn returned {len(result)}-tuple, expected 2"
        passed, reasons = result
        assert isinstance(passed, bool), f"passed is {type(passed)}, expected bool"
        assert isinstance(reasons, list), f"reasons is {type(reasons)}, expected list"


# ============================================================
# ORACLE FAILURE SENSITIVITY (buggy code must fail)
# ============================================================


class TestOracleFailsBuggy:
    """Buggy code must fail every test oracle. If it passes, the oracle is too weak."""

    @pytest.mark.parametrize("case_id", CASE_IDS)
    def test_oracle_fails_buggy_code(self, case_id):
        case = next(c for c in ALL_CASES if c["id"] == case_id)
        code = load_case_code(case)
        result = exec_evaluate(case, code)
        assert result["pass"] is False, (
            f"Buggy code PASSES for {case_id} — oracle is too weak. "
            f"Result: {result.get('reasons', [])}"
        )


# ============================================================
# ORACLE PASSES REFERENCE FIXES
# ============================================================

# Cases with known reference_fix metadata issues (function field mismatch).
# These are real data quality issues caught by L-1, tracked for fix.
KNOWN_REF_FIX_ISSUES = {
    "mutable_default_b",  # reference_fix.function=enqueue but fix is in worker.py (process_batch)
}


class TestOraclePassesRef:
    """Reference fixes must pass every test oracle."""

    @pytest.mark.parametrize("case_id", CASE_IDS)
    def test_oracle_passes_reference_fix(self, case_id):
        if case_id in KNOWN_REF_FIX_ISSUES:
            pytest.skip(f"Known reference_fix metadata issue: {case_id}")
        case = next(c for c in ALL_CASES if c["id"] == case_id)
        ref_code = load_reference_code(case)
        assert ref_code is not None, f"No reference fix for {case_id}"
        result = exec_evaluate(case, ref_code)
        assert result["pass"] is True, (
            f"Reference fix FAILS for {case_id} — oracle or fix is broken. "
            f"Reasons: {result.get('reasons', [])}. "
            f"Execution: {result.get('execution', {})}"
        )


# ============================================================
# ADVERSARIAL PERTURBATION (failure sensitivity proof)
# ============================================================

# Perturbations: map case_id -> (pattern_to_find, replacement) in reference fix
# Each reverts the key fix line to reintroduce the bug
PERTURBATIONS = {
    "alias_config_a": ("DEFAULTS.copy()", "DEFAULTS"),
    "stale_cache_a": ("_cache.pop(product_id, None)", "# _cache.pop(product_id, None)"),
    "mutable_default_a": ("if queue is None:", "if False:"),
    "partial_update_a": ('user["display_name"] = value', '# user["display_name"] = value'),
    "check_then_act": ("if check_balance(name, amount):", "if True:"),
}


class TestOracleAdversarial:
    """Slightly broken code must fail the oracle."""

    @pytest.mark.parametrize("case_id", list(PERTURBATIONS.keys()))
    def test_oracle_catches_perturbation(self, case_id):
        case = next(c for c in ALL_CASES if c["id"] == case_id)
        ref_code = load_reference_code(case)
        assert ref_code is not None

        pattern, replacement = PERTURBATIONS[case_id]
        assert (
            pattern in ref_code
        ), f"Perturbation pattern '{pattern}' not found in reference fix for {case_id}"

        perturbed = ref_code.replace(pattern, replacement, 1)
        assert perturbed != ref_code, "Perturbation had no effect"

        result = exec_evaluate(case, perturbed)
        assert result["pass"] is False, (
            f"Perturbed code PASSES for {case_id} — oracle has zero failure sensitivity. "
            f"Perturbation: '{pattern}' → '{replacement}'"
        )


# ============================================================
# ZERO-SENSITIVITY GUARD
# ============================================================


class TestNoZeroSensitivity:
    """No case should have both buggy and reference producing the same result."""

    @pytest.mark.parametrize("case_id", CASE_IDS)
    def test_oracle_distinguishes_correct_from_incorrect(self, case_id):
        if case_id in KNOWN_REF_FIX_ISSUES:
            pytest.skip(f"Known reference_fix metadata issue: {case_id}")
        case = next(c for c in ALL_CASES if c["id"] == case_id)
        buggy_code = load_case_code(case)
        ref_code = load_reference_code(case)
        assert ref_code is not None

        buggy_result = exec_evaluate(case, buggy_code)
        ref_result = exec_evaluate(case, ref_code)

        assert buggy_result["pass"] != ref_result["pass"], (
            f"Zero sensitivity for {case_id}: "
            f"buggy pass={buggy_result['pass']}, ref pass={ref_result['pass']}. "
            f"Oracle cannot distinguish correct from incorrect."
        )
