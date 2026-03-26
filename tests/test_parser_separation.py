"""Tests for parser-evaluation separation (plan v3).

Validates that code extraction is independent from metadata validation,
and that no valid solution is discarded due to schema rigidity.
"""

import ast
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from leg_reduction import parse_leg_reduction_output, _extraction_fail
from retry_harness import _select_best_code


# ============================================================
# Helpers: build LEG responses
# ============================================================

def _leg_response(code="def f(): return 1", diagnosis="bug found",
                  plan_steps=None, revision_history=None,
                  verification=None, internal_revisions=0,
                  extra_fields=None, changes_made_override=None):
    """Build a LEG-reduction JSON response string."""
    if plan_steps is None:
        plan_steps = [{"step": "fix it", "intended_effect": "correct behavior"}]
    if revision_history is None:
        revision_history = [{
            "revision": 0,
            "verification": [{"step": "fix it", "status": "PASS", "evidence": "works"}],
            "invariants_checked": [],
            "issues_found": [],
            "changes_made": changes_made_override,
            "changed_functions": [],
            "code_before": "old code",
            "code_after": code,
        }]
    if verification is None:
        verification = [{"step": "fix it", "status": "PASS", "evidence": "works"}]

    d = {
        "bug_diagnosis": diagnosis,
        "plan_steps": plan_steps,
        "revision_history": revision_history,
        "verification": verification,
        "code": code,
        "internal_revisions": internal_revisions,
    }
    if extra_fields:
        d.update(extra_fields)
    return json.dumps(d)


# ============================================================
# Test 1: Valid JSON + wrong metadata → code MUST still execute
# ============================================================

class TestMetadataTolerance:

    def test_missing_target_in_changes_made(self):
        """Changes_made missing 'target' → schema_compliant=False, code extracted."""
        resp = _leg_response(
            code="def create_config():\n    return dict(DEFAULTS)",
            changes_made_override=[{"change_type": "modify", "description": "return copy"}],
        )
        result = parse_leg_reduction_output(resp)
        assert result["code_extracted"] is True
        assert result["parse_error"] is None
        assert result["schema_compliant"] is False
        assert len(result["schema_violations"]) > 0
        assert result["code"] == "def create_config():\n    return dict(DEFAULTS)"

    def test_count_mismatch(self):
        """internal_revisions doesn't match revision_history length."""
        resp = _leg_response(
            code="def f(): return 1",
            internal_revisions=5,  # mismatch: should be 0 for 1 revision
        )
        result = parse_leg_reduction_output(resp)
        assert result["code_extracted"] is True
        assert result["parse_error"] is None
        assert result["schema_compliant"] is False
        assert any("internal_revisions" in v for v in result["schema_violations"])


# ============================================================
# Test 2: Valid JSON + correct code → must pass
# ============================================================

    def test_perfect_response(self):
        """All fields correct → schema_compliant=True, code_extracted=True."""
        resp = _leg_response(code="def f():\n    return 42")
        result = parse_leg_reduction_output(resp)
        assert result["code_extracted"] is True
        assert result["parse_error"] is None
        assert result["code"] == "def f():\n    return 42"


# ============================================================
# Test 3: Invalid JSON → must fail cleanly
# ============================================================

class TestJsonFailure:

    def test_broken_json_no_code_anywhere(self):
        """Completely empty malformed text → code_extracted=False."""
        result = parse_leg_reduction_output('   ')
        assert result["code_extracted"] is False
        assert result["parse_error"] is not None

    def test_broken_json_fallback_recovers(self):
        """Malformed JSON triggers fallback. raw_fallback may extract raw text as code."""
        result = parse_leg_reduction_output('{"bug_diagnosis": "x", "code":')
        # Fallback fires and extracts SOMETHING (even if garbage)
        # This is extraction succeeding (fallback path), not a hard failure
        assert result["extraction_source"] == "fallback"
        assert result["schema_compliant"] is False

    def test_empty_response(self):
        result = parse_leg_reduction_output("")
        assert result["code_extracted"] is False
        assert result["parse_error"] is not None


# ============================================================
# Test 4: Extra fields → must NOT cause failure
# ============================================================

class TestExtraFields:

    def test_extra_fields_ignored(self):
        """Extra fields in JSON do not cause failure."""
        resp = _leg_response(
            code="def f(): return 1",
            extra_fields={"confidence": 0.95, "model_notes": "looks good", "extra": {}},
        )
        result = parse_leg_reduction_output(resp)
        assert result["code_extracted"] is True
        assert result["parse_error"] is None
        # Extra fields don't make schema non-compliant (only missing/wrong fields do)


# ============================================================
# Test 7: Cross-model consistency
# ============================================================

class TestCrossModelConsistency:

    def test_same_code_different_metadata(self):
        """Two responses with identical code but different metadata quality
        must extract the same code."""
        code = "def create_config():\n    return dict(DEFAULTS)"

        # Response A: perfect metadata
        resp_a = _leg_response(code=code)
        # Response B: metadata has violations
        resp_b = _leg_response(
            code=code,
            internal_revisions=99,
            changes_made_override=[{"change_type": "modify"}],  # missing target
        )

        result_a = parse_leg_reduction_output(resp_a)
        result_b = parse_leg_reduction_output(resp_b)

        assert result_a["code"] == result_b["code"]
        assert result_a["code_extracted"] == result_b["code_extracted"] == True
        assert result_a["schema_compliant"] is True
        assert result_b["schema_compliant"] is False


# ============================================================
# Test 8: Execution equivalence (LEG path)
# ============================================================

class TestLegExecutionEquivalence:

    def test_code_unchanged_by_metadata_fix(self):
        """For metadata-error cases, extracted code is byte-identical."""
        # Simulate a case with metadata errors
        resp = _leg_response(
            code="def process(data):\n    return sorted(data)",
            internal_revisions=3,  # wrong count
            changes_made_override=[{"change_type": "add"}],  # missing fields
        )
        result = parse_leg_reduction_output(resp)
        assert result["code"] == "def process(data):\n    return sorted(data)"
        assert result["code_extracted"] is True
        assert result["extraction_source"] == "strict"


# ============================================================
# Test 13-15: Extraction selection (retry harness)
# ============================================================

class TestExtractionSelection:

    def test_strict_wins_when_both_same(self):
        """Both produce same code → strict, no conflict."""
        code = "def f():\n    return 42"
        selected, source, conflict, candidates = _select_best_code(code, code)
        assert source == "strict"
        assert conflict is False

    def test_fallback_wins_when_strict_is_placeholder(self):
        """Strict has placeholder, fallback has real code."""
        placeholder = "# your code here"
        real_code = "def create_config():\n    return dict(DEFAULTS)\n" + "# padding " * 10
        selected, source, conflict, candidates = _select_best_code(placeholder, real_code)
        assert source == "fallback"
        assert conflict is True
        assert "def create_config" in selected

    def test_strict_wins_when_fallback_is_garbage(self):
        """Strict has valid code, fallback is not valid Python."""
        valid = "def f():\n    return 42\n" + "# padding " * 10
        garbage = "This is just text, not code at all {{{ broken"
        selected, source, conflict, candidates = _select_best_code(valid, garbage)
        assert source == "strict"
        assert conflict is True

    def test_both_empty(self):
        """Both empty → empty result."""
        selected, source, conflict, candidates = _select_best_code("", "")
        assert selected == ""
        assert source == "none"

    def test_only_strict(self):
        """Only strict has code."""
        code = "def f(): pass"
        selected, source, conflict, candidates = _select_best_code(code, "")
        assert source == "strict"
        assert conflict is False

    def test_only_fallback(self):
        """Only fallback has code."""
        code = "def f(): pass"
        selected, source, conflict, candidates = _select_best_code("", code)
        assert source == "fallback"
        assert conflict is False

    def test_longer_wins_tiebreaker(self):
        """Two valid non-trivial candidates → longer wins."""
        short = "def f():\n    return 1\n" + "# pad " * 10
        long = "def f():\n    x = compute()\n    y = transform(x)\n    return y\n" + "# pad " * 20
        selected, source, conflict, candidates = _select_best_code(short, long)
        assert conflict is True
        assert len(selected) == len(long)


# ============================================================
# Test 16: LEG restricted fallback — code recovered from broken JSON
# ============================================================

class TestLegRestrictedFallback:

    def test_broken_json_with_code_block(self):
        """JSON is malformed but raw output has a ```python block."""
        raw = '{"bug_diagnosis": "aliasing", "code": BROKEN\n```python\ndef create_config():\n    return dict(DEFAULTS)\n```'
        result = parse_leg_reduction_output(raw)
        assert result["code_extracted"] is True
        assert result["extraction_source"] == "fallback"
        assert result["schema_compliant"] is False
        assert result["parse_error"] is None
        assert "create_config" in result["code"]

    def test_no_json_at_all(self):
        """No JSON, but code block present."""
        raw = 'Here is the fix:\n```python\ndef f():\n    return 42\n```'
        result = parse_leg_reduction_output(raw)
        assert result["code_extracted"] is True
        assert result["extraction_source"] == "fallback"


# ============================================================
# Test 17: LEG fallback does NOT override valid JSON
# ============================================================

    def test_valid_json_no_fallback(self):
        """When JSON extraction succeeds, fallback must NOT run."""
        resp = _leg_response(code="def f(): return 1")
        result = parse_leg_reduction_output(resp)
        assert result["extraction_source"] == "strict"
        assert result["code_extracted"] is True


# ============================================================
# Test 18: Extraction conflict logging
# ============================================================

class TestExtractionConflict:

    def test_conflict_detected_and_logged(self):
        """Two different non-empty candidates → conflict=True, candidates logged."""
        code_a = "def f():\n    return 1\n" + "# a " * 15
        code_b = "def g():\n    return 2\n" + "# b " * 15
        selected, source, conflict, candidates = _select_best_code(code_a, code_b)
        assert conflict is True
        assert len(candidates) == 2
        assert "strict" in candidates
        assert "fallback" in candidates


# ============================================================
# Test: _extraction_fail has all required fields
# ============================================================

class TestExtractionFailFields:

    def test_extraction_fail_has_new_fields(self):
        result = _extraction_fail("test error")
        assert result["code_extracted"] is False
        assert result["schema_compliant"] is False
        assert "schema_violations" in result
        assert result["extraction_source"] is None
        assert result["parse_error"] == "test error"


# ============================================================
# Test 10: No salvage in primary path (structural check)
# ============================================================

class TestNoSalvage:

    def test_reconstruct_salvage_not_imported_in_execution(self):
        """reconstructor.reconstruct_salvage must not be called in execution.py primary path."""
        import execution
        import inspect
        source = inspect.getsource(execution._do_reconstruction)
        assert "reconstruct_salvage" not in source, (
            "reconstruct_salvage found in _do_reconstruction — "
            "salvage must not be used in primary evaluation path"
        )
