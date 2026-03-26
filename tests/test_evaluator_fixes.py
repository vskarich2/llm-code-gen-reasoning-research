"""Tests for Fix D (parse gate) and Fix E (eval_model bug fix).

These are Go/No-Go prerequisite tests per plan v6 Section 17.
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluator import (
    llm_classify, classify_parse_category,
    _CLASSIFICATION_DISALLOWED,
)


class _MockEvalConfig:
    """Mock evaluator config for tests."""
    name = "test-default-model"
    max_task_chars = 800
    max_code_chars = 2000
    max_reasoning_chars = 1000


class _MockModels:
    evaluator = _MockEvalConfig()


class _MockConfig:
    models = _MockModels()


@pytest.fixture(autouse=True)
def _mock_eval_model_config():
    """Mock config so tests don't require loaded experiment config."""
    with patch("evaluator._get_eval_model", return_value="test-default-model"), \
         patch("evaluator.get_config", return_value=_MockConfig(), create=True):
        # Also patch the import inside llm_classify
        with patch.dict("sys.modules", {"experiment_config": MagicMock(get_config=lambda: _MockConfig())}):
            yield


# ============================================================
# Fix E: eval_model parameter honored
# ============================================================

class TestEvalModelFix:
    """Verify evaluator.py no longer ignores the eval_model parameter."""

    def test_eval_model_parameter_honored(self):
        """If eval_model is passed, it MUST be used, not the default."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "YES ; HIDDEN_DEPENDENCY"
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning="The bug is aliasing",
                eval_model="test-model-override",
            )
            # The call_model must have been called with model="test-model-override"
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args
            assert call_kwargs[1]["model"] == "test-model-override", (
                f"eval_model was ignored. Actual model used: {call_kwargs[1]['model']}"
            )

    def test_eval_model_default_when_none(self):
        """If eval_model is None, the config default model is used."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "YES ; HIDDEN_DEPENDENCY"
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning="The bug is aliasing",
                eval_model=None,
            )
            call_kwargs = mock_call.call_args
            # Should use whatever _get_eval_model() returns (config-based)
            assert call_kwargs[1]["model"] is not None
            assert isinstance(call_kwargs[1]["model"], str)

    def test_eval_model_logged_in_result(self):
        """Result must contain eval_model_actual field."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "YES ; HIDDEN_DEPENDENCY"
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning="The bug is aliasing",
                eval_model="my-model",
            )
            assert "eval_model_actual" in result
            assert result["eval_model_actual"] == "my-model"

    def test_eval_model_logged_on_exception(self):
        """Even on exception, eval_model_actual is logged."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.side_effect = RuntimeError("API down")
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning="The bug is aliasing",
                eval_model="crash-model",
            )
            assert result["eval_model_actual"] == "crash-model"
            assert result["reasoning_correct"] is None

    def test_no_hardcoded_model_in_source(self):
        """The hard-coded model string must not appear as a direct assignment
        inside llm_classify (except as the default constant)."""
        import inspect
        source = inspect.getsource(llm_classify)
        # The old bug: `model = "gpt-5.4-mini"` directly in function body
        # The fix: `model = eval_model or _get_eval_model()`
        # Check there's no bare assignment to a string literal
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("model =") and '"gpt-' in stripped:
                # This is the old bug pattern
                pytest.fail(
                    f"Hard-coded model found in llm_classify: {stripped!r}. "
                    f"eval_model parameter must be used."
                )


# ============================================================
# Fix D: Parse gate
# ============================================================

class TestParseGate:
    """Verify the parse gate prevents classification on corrupt reasoning."""

    def test_reasoning_lost_produces_none(self):
        """REASONING_LOST: reasoning empty + parse_error -> None, not False."""
        result = llm_classify(
            case={"id": "test", "task": "fix"},
            code="def f(): pass",
            reasoning="",
            parse_error="extraction_error: NO_JSON_OBJECT_FOUND",
        )
        assert result["reasoning_correct"] is None, (
            f"Expected None for REASONING_LOST, got {result['reasoning_correct']}"
        )
        assert "GATED" in result["classify_parse_error"]
        assert result["parse_category"] == "REASONING_LOST"

    def test_structure_missing_produces_none(self):
        """STRUCTURE_MISSING: schema parse failure -> None."""
        result = llm_classify(
            case={"id": "test", "task": "fix"},
            code="def f(): pass",
            reasoning="",
            parse_error="STRUCTURE_MISSING: missing revision_history",
        )
        assert result["reasoning_correct"] is None
        assert result["parse_category"] == "STRUCTURE_MISSING"

    def test_code_lost_produces_none(self):
        """CODE_LOST: raw_fallback with empty reasoning -> None."""
        result = llm_classify(
            case={"id": "test", "task": "fix"},
            code="raw text that is not code",
            reasoning="",
            parse_error="SEVERE: raw_fallback",
            raw_fallback=True,
        )
        assert result["reasoning_correct"] is None
        assert result["parse_category"] == "CODE_LOST"

    def test_empty_reasoning_no_parse_error_classifies_normally(self):
        """Empty reasoning WITHOUT parse_error is legitimate empty reasoning.
        The classifier should run and return a verdict (likely NO)."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "NO ; UNKNOWN"
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning="",
                parse_error=None,
            )
            # Classifier should have been called
            mock_call.assert_called_once()
            # Note: empty reasoning with no parse error could be REASONING_LOST
            # but the policy is: no parse_error means it's genuine empty reasoning

    def test_nonempty_reasoning_with_parse_error_classifies(self):
        """If reasoning IS present despite a parse_error, classification proceeds."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "YES ; HIDDEN_DEPENDENCY"
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning="The bug is shared mutable state",
                parse_error="lenient-json: extracted from malformed JSON",
            )
            # Classifier should run because reasoning is non-empty
            mock_call.assert_called_once()
            assert result["reasoning_correct"] is True
            assert result["parse_category"] in ("PARTIAL_JSON_RECOVERED", "MALFORMED_BUT_RECOVERED")

    def test_parse_gate_never_produces_false_on_lost_reasoning(self):
        """The parse gate must NEVER produce reasoning_correct=False
        when the reasoning was lost due to parsing."""
        for parse_err in [
            "extraction_error: NO_JSON_OBJECT_FOUND",
            "extraction_error: UNBALANCED_JSON",
            "missing_key: reasoning",
            "STRUCTURE_MISSING: missing revision_history",
            "SEVERE: raw_fallback — no code blocks found",
        ]:
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning="",
                parse_error=parse_err,
            )
            assert result["reasoning_correct"] is not False, (
                f"Parse gate failed: reasoning_correct=False for parse_error={parse_err!r}. "
                f"Must be None, not False."
            )


# ============================================================
# Parse category classification
# ============================================================

class TestParseCategoryClassification:
    """Test the parse category classification logic."""

    def test_clean(self):
        assert classify_parse_category("valid reasoning", None) == "CLEAN"

    def test_reasoning_lost(self):
        assert classify_parse_category("", "some error") == "REASONING_LOST"

    def test_reasoning_lost_none_reasoning(self):
        cat = classify_parse_category("", "missing_key: reasoning")
        assert cat == "REASONING_LOST"

    def test_structure_missing(self):
        cat = classify_parse_category("", "STRUCTURE_MISSING: bad schema")
        assert cat == "STRUCTURE_MISSING"

    def test_code_lost(self):
        cat = classify_parse_category("", "SEVERE: raw_fallback", raw_fallback=True)
        assert cat == "CODE_LOST"

    def test_partial_json_recovered(self):
        cat = classify_parse_category("some reasoning", "lenient-json: extracted")
        assert cat == "PARTIAL_JSON_RECOVERED"

    def test_malformed_but_recovered(self):
        cat = classify_parse_category("some reasoning", "non-json: extracted from code block")
        assert cat == "MALFORMED_BUT_RECOVERED"

    def test_disallowed_categories(self):
        """Verify the DISALLOWED set matches expected categories."""
        assert "REASONING_LOST" in _CLASSIFICATION_DISALLOWED
        assert "CODE_LOST" in _CLASSIFICATION_DISALLOWED
        assert "STRUCTURE_MISSING" in _CLASSIFICATION_DISALLOWED
        assert "CLEAN" not in _CLASSIFICATION_DISALLOWED


# ============================================================
# Result field completeness
# ============================================================

class TestResultFields:
    """Verify all required fields are present in results."""

    def test_result_has_eval_model_actual(self):
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "YES ; HIDDEN_DEPENDENCY"
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="pass",
                reasoning="aliasing bug",
            )
            assert "eval_model_actual" in result
            assert "parse_category" in result

    def test_gated_result_has_all_fields(self):
        result = llm_classify(
            case={"id": "test", "task": "fix"},
            code="pass",
            reasoning="",
            parse_error="extraction_error",
        )
        assert "eval_model_actual" in result
        assert "parse_category" in result
        assert "reasoning_correct" in result
        assert "failure_type" in result
        assert "classify_raw" in result
        assert "classify_parse_error" in result


# ============================================================
# Holdout integrity
# ============================================================

class TestHoldoutIntegrity:
    """Verify holdout, locked, and phase0 case sets don't overlap."""

    def test_no_overlap(self):
        holdout = json.load(open("audit/holdout_set.json"))
        locked = json.load(open("audit/locked_audit_set.json"))
        phase0 = json.load(open("audit/phase0_case_set.json"))

        h_ids = {c["case_id"] for c in holdout}
        l_ids = {c["case_id"] for c in locked}
        p_ids = {c["case_id"] for c in phase0}

        assert len(h_ids & l_ids) == 0, f"Holdout/locked overlap: {h_ids & l_ids}"
        assert len(h_ids & p_ids) == 0, f"Holdout/phase0 overlap: {h_ids & p_ids}"

    def test_exhaustive(self):
        holdout = json.load(open("audit/holdout_set.json"))
        locked = json.load(open("audit/locked_audit_set.json"))
        phase0 = json.load(open("audit/phase0_case_set.json"))
        cases = json.load(open("cases_v2.json"))

        all_audit = {c["case_id"] for c in holdout + locked + phase0}
        all_cases = {c["id"] for c in cases}
        assert all_audit == all_cases, f"Missing: {all_cases - all_audit}"

    def test_holdout_size(self):
        holdout = json.load(open("audit/holdout_set.json"))
        assert len(holdout) == 8

    def test_locked_size(self):
        locked = json.load(open("audit/locked_audit_set.json"))
        assert len(locked) == 30
