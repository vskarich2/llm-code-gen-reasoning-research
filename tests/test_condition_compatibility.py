"""Tests for condition compatibility enforcement.

Verifies that:
1. Incompatible (case, condition) pairs are blocked
2. Missing nudge mappings cause hard failures
3. No condition can silently degrade to baseline
4. Universal conditions work on all cases
5. Restricted conditions fail on unmapped cases
6. Registry covers all known conditions

Run: .venv/bin/python -m pytest tests/test_condition_compatibility.py -v
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from condition_registry import (
    CONDITION_SPECS,
    check_compatibility,
    validate_run,
    get_safe_conditions,
    get_condition_sets,
)

BASE = Path(__file__).resolve().parents[1]
_ALL_CASES = json.loads((BASE / "cases_v2.json").read_text())


# ============================================================
# TEST 1: Registry covers all conditions known to runner.py
# ============================================================

class TestRegistryCompleteness:
    def test_all_conditions_registered(self):
        """Every condition in runner.py's ALL_CONDITIONS must be in the registry."""
        sys.path.insert(0, str(BASE))
        from runner import ALL_CONDITIONS
        for cond in ALL_CONDITIONS:
            assert cond in CONDITION_SPECS, (
                f"Condition '{cond}' is in ALL_CONDITIONS but NOT in CONDITION_SPECS. "
                f"It can run without compatibility checking."
            )

    def test_no_unknown_conditions_in_registry(self):
        """Every condition in the registry should be in ALL_CONDITIONS."""
        from runner import ALL_CONDITIONS
        valid = set(ALL_CONDITIONS)
        for cond in CONDITION_SPECS:
            assert cond in valid, (
                f"Condition '{cond}' is in CONDITION_SPECS but NOT in ALL_CONDITIONS."
            )


# ============================================================
# TEST 2: Universal conditions work on ALL cases
# ============================================================

class TestUniversalConditions:
    @pytest.mark.parametrize("cond", get_condition_sets()["universal"])
    def test_universal_on_all_cases(self, cond):
        """Universal conditions must be compatible with every case."""
        for case in _ALL_CASES:
            ok, reason = check_compatibility(case, cond)
            assert ok, (
                f"Universal condition '{cond}' rejected case '{case['id']}': {reason}"
            )


# ============================================================
# TEST 3: Restricted conditions fail on unmapped cases
# ============================================================

class TestRestrictedConditionsFail:
    def test_diagnostic_fails_on_unmapped_case(self):
        """diagnostic must fail on a case without nudge mapping."""
        # Find an unmapped case
        from nudges.mapping import CASE_TO_OPERATORS
        unmapped = [c for c in _ALL_CASES if c["id"] not in CASE_TO_OPERATORS]
        assert unmapped, "All cases are mapped — can't test unmapped failure"
        ok, reason = check_compatibility(unmapped[0], "diagnostic")
        assert not ok, (
            f"diagnostic should be INCOMPATIBLE with unmapped case '{unmapped[0]['id']}'"
        )
        assert "CASE_TO_OPERATORS" in reason

    def test_guardrail_fails_on_unmapped_case(self):
        from nudges.mapping import CASE_TO_OPERATORS
        unmapped = [c for c in _ALL_CASES if c["id"] not in CASE_TO_OPERATORS]
        assert unmapped
        ok, reason = check_compatibility(unmapped[0], "guardrail")
        assert not ok

    def test_scm_fails_on_unmapped_case(self):
        """SCM conditions must fail on cases without SCM data."""
        from scm_data import get_scm
        no_scm = [c for c in _ALL_CASES if get_scm(c["id"]) is None]
        assert no_scm
        for cond in ["scm_descriptive", "scm_constrained", "scm_constrained_evidence"]:
            ok, reason = check_compatibility(no_scm[0], cond)
            assert not ok, f"SCM condition '{cond}' should fail on '{no_scm[0]['id']}'"


# ============================================================
# TEST 4: validate_run blocks incompatible experiments
# ============================================================

class TestValidateRunBlocks:
    def test_incompatible_experiment_raises(self):
        """Running diagnostic on all cases must raise (most lack mappings)."""
        with pytest.raises(RuntimeError, match="PRE-FLIGHT FAILED"):
            validate_run(_ALL_CASES, ["diagnostic"])

    def test_compatible_experiment_passes(self):
        """Running baseline on all cases must succeed."""
        validate_run(_ALL_CASES, ["baseline"])  # should not raise

    def test_universal_conditions_pass(self):
        """All universal conditions on all cases must pass."""
        universal = get_condition_sets()["universal"]
        validate_run(_ALL_CASES, universal)  # should not raise


# ============================================================
# TEST 5: Nudge router crashes on unmapped cases (no silent degradation)
# ============================================================

class TestNudgeRouterCrashes:
    def test_apply_diagnostic_crashes_on_unmapped(self):
        """apply_diagnostic must raise RuntimeError for unmapped case."""
        from nudges.router import apply_diagnostic
        from nudges.mapping import CASE_TO_OPERATORS
        unmapped = [c for c in _ALL_CASES if c["id"] not in CASE_TO_OPERATORS]
        assert unmapped
        with pytest.raises(RuntimeError, match="CONDITION INTEGRITY FAILURE"):
            apply_diagnostic(unmapped[0]["id"], "test prompt")

    def test_apply_guardrail_crashes_on_unmapped(self):
        from nudges.router import apply_guardrail
        from nudges.mapping import CASE_TO_OPERATORS
        unmapped = [c for c in _ALL_CASES if c["id"] not in CASE_TO_OPERATORS]
        assert unmapped
        with pytest.raises(RuntimeError, match="CONDITION INTEGRITY FAILURE"):
            apply_guardrail(unmapped[0]["id"], "test prompt")

    def test_diagnostic_never_returns_base_prompt(self):
        """For mapped cases, diagnostic must actually modify the prompt."""
        from nudges.router import apply_diagnostic
        from nudges.mapping import CASE_TO_OPERATORS
        base = "This is the base prompt for testing."
        for case_id in CASE_TO_OPERATORS:
            result = apply_diagnostic(case_id, base)
            assert result != base, (
                f"apply_diagnostic returned UNCHANGED prompt for mapped case '{case_id}'"
            )


# ============================================================
# TEST 6: get_safe_conditions returns only truly safe conditions
# ============================================================

class TestSafeConditions:
    def test_restricted_nudge_not_in_safe(self):
        """Conditions requiring nudge mappings must NOT be safe for all cases."""
        safe = set(get_safe_conditions(_ALL_CASES))
        assert "diagnostic" not in safe, "diagnostic should not be safe for all cases"
        assert "guardrail" not in safe, "guardrail should not be safe for all cases"

    def test_restricted_scm_not_in_safe(self):
        """SCM conditions must NOT be safe for all cases."""
        safe = set(get_safe_conditions(_ALL_CASES))
        assert "scm_descriptive" not in safe, "scm_descriptive should not be safe for all cases"

    def test_baseline_always_safe(self):
        safe = set(get_safe_conditions(_ALL_CASES))
        assert "baseline" in safe


# ============================================================
# TEST 7: Unknown condition is rejected
# ============================================================

class TestUnknownCondition:
    def test_unknown_condition_fails(self):
        ok, reason = check_compatibility(_ALL_CASES[0], "nonexistent_condition")
        assert not ok
        assert "Unknown condition" in reason
