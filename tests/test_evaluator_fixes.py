"""Tests for evaluator: reasoning gate, eval_model routing, parse categories.

Updated for schema v2 (structured reasoning, multi-dimensional classifier).
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluator import (
    llm_classify,
    classify_parse_category,
    _CLASSIFICATION_DISALLOWED,
)


class _MockEvalConfig:
    """Mock evaluator config for tests."""

    name = "test-default-model"
    max_task_chars = 800
    max_code_chars = 2000
    max_reasoning_chars = 1000


class _MockEvaluationConfig:
    classifier_mode = "blind"
    reasoning_correct_mode = "strict"


class _MockModels:
    evaluator = _MockEvalConfig()


class _MockConfig:
    models = _MockModels()
    evaluation = _MockEvaluationConfig()


def _make_reasoning_obj(root_cause="", failure_mechanism="", broken_invariant="", fix_strategy=""):
    """Helper: build a reasoning_obj dict."""
    return {
        "root_cause": root_cause,
        "failure_mechanism": failure_mechanism,
        "broken_invariant": broken_invariant,
        "fix_strategy": fix_strategy,
        "self_check": "",
        "revision_note": None,
        "attempt_number": 0,
        "previous_attempt_summary": None,
    }


def _make_validation(attempted=True, present=True):
    """Helper: build a reasoning_validation dict."""
    return {
        "reasoning_attempted": attempted,
        "reasoning_present": present,
        "reasoning_lengths": {},
    }


_PRESENT_OBJ = _make_reasoning_obj(
    root_cause="shared mutable default arg",
    failure_mechanism="dict reference shared across calls",
    broken_invariant="each call must get independent state",
    fix_strategy="use None default and create new dict",
)
_PRESENT_VAL = _make_validation(attempted=True, present=True)
_ABSENT_VAL = _make_validation(attempted=False, present=False)


@pytest.fixture(autouse=True)
def _mock_eval_model_config():
    """Mock config so tests don't require loaded experiment config."""
    from prompt_registry import load_prompt_registry, _loaded
    if not _loaded:
        load_prompt_registry()

    with (
        patch("evaluator._get_eval_model", return_value="test-default-model"),
    ):
        with patch.dict(
            "sys.modules", {"experiment_config": MagicMock(get_config=lambda: _MockConfig())}
        ):
            yield


# ============================================================
# Fix E: eval_model parameter honored
# ============================================================


class TestEvalModelFix:
    """Verify evaluator.py honors the eval_model parameter."""

    def test_eval_model_parameter_honored(self):
        """If eval_model is passed, it MUST be used, not the default."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY\nHIGH\nCounterfactual: Removing cause fixes it.\nEvidence: config = DEFAULTS creates alias.\nJudgment: Correct reasoning."
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
                eval_model="test-model-override",
            )
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args
            assert (
                call_kwargs[1]["model"] == "test-model-override"
            ), f"eval_model was ignored. Actual model used: {call_kwargs[1]['model']}"

    def test_eval_model_default_when_none(self):
        """If eval_model is None, the config default model is used."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY\nHIGH\nCounterfactual: Removing cause fixes it.\nEvidence: alias on line 5.\nJudgment: Correct."
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
                eval_model=None,
            )
            call_kwargs = mock_call.call_args
            assert call_kwargs[1]["model"] is not None
            assert isinstance(call_kwargs[1]["model"], str)

    def test_eval_model_logged_in_result(self):
        """Result must contain eval_model_actual field."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY\nHIGH\nCounterfactual: Removing cause fixes it.\nEvidence: alias on line 5.\nJudgment: Correct."
            result = llm_classify(
                case={"id": "test", "task": "fix bug"},
                code="def f(): pass",
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
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
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
                eval_model="crash-model",
            )
            assert result["eval_model_actual"] == "crash-model"
            assert result["reasoning_correct"] is None

    def test_no_hardcoded_model_in_source(self):
        """No hard-coded model string in llm_classify."""
        import inspect

        source = inspect.getsource(llm_classify)
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("model =") and '"gpt-' in stripped:
                pytest.fail(
                    f"Hard-coded model found in llm_classify: {stripped!r}. "
                    f"eval_model parameter must be used."
                )


# ============================================================
# Fix D: Parse gate
# ============================================================


class TestReasoningGate:
    """Verify the reasoning gate prevents classification when reasoning is absent."""

    def test_absent_reasoning_produces_none(self):
        """reasoning_present=False → reasoning_correct=None, classifier NOT called."""
        with patch("evaluator.call_model") as mock_call:
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning_obj=_make_reasoning_obj(),
                reasoning_validation=_ABSENT_VAL,
            )
            mock_call.assert_not_called()
            assert result["reasoning_correct"] is None

    def test_present_reasoning_calls_classifier(self):
        """reasoning_present=True → classifier IS called."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY\nHIGH\nCounterfactual: Removing cause fixes it.\nEvidence: alias on line 5.\nJudgment: Correct."
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
            )
            mock_call.assert_called_once()
            assert result["reasoning_correct"] is True

    def test_gate_returns_null_classifier_fields(self):
        """Gated result must have all NULL_CLASSIFIER_RESULT fields."""
        result = llm_classify(
            case={"id": "test", "task": "fix"},
            code="def f(): pass",
            reasoning_obj=_make_reasoning_obj(),
            reasoning_validation=_ABSENT_VAL,
        )
        assert result["mechanism_identified"] is None
        assert result["invariant_identified"] is None
        assert result["fix_alignment"] is None
        assert result["reasoning_code_alignment"] is None
        assert result["failure_type"] is None
        assert result["confidence"] is None
        assert result["reasoning_correct"] is None

    def test_gate_never_produces_false(self):
        """The gate must NEVER produce reasoning_correct=False."""
        for present in [False]:
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning_obj=_make_reasoning_obj(),
                reasoning_validation=_make_validation(present=present),
            )
            assert result["reasoning_correct"] is not False, (
                f"Gate produced reasoning_correct=False for present={present}. Must be None."
            )

    def test_classifier_returns_multi_dimensional_result(self):
        """Successful classification returns all 4 dimensions."""
        with patch("evaluator.call_model") as mock_call:
            mock_call.return_value = "CORRECT;PARTIAL;CORRECT;CORRECT;WRONG;HIDDEN_DEPENDENCY\nMEDIUM\nCounterfactual: x.\nEvidence: y.\nJudgment: Partial match."
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="def f(): pass",
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
            )
            assert result["mechanism_identified"] == "CORRECT"
            assert result["invariant_identified"] == "PARTIAL"
            assert result["fix_alignment"] == "CORRECT"
            assert result["reasoning_code_alignment"] == "WRONG"
            assert result["failure_type"] == "HIDDEN_DEPENDENCY"
            assert result["confidence"] == "MEDIUM"
            assert result["reasoning_correct"] is True  # strict: mechanism=YES, invariant=PARTIAL, fix=YES


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
            mock_call.return_value = "CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY\nHIGH\nCounterfactual: Removing cause fixes it.\nEvidence: alias on line 5.\nJudgment: Correct."
            result = llm_classify(
                case={"id": "test", "task": "fix"},
                code="pass",
                reasoning_obj=_PRESENT_OBJ,
                reasoning_validation=_PRESENT_VAL,
            )
            assert "eval_model_actual" in result
            assert "classifier_mode" in result
            assert "reasoning_correct_mode" in result

    def test_gated_result_has_all_fields(self):
        result = llm_classify(
            case={"id": "test", "task": "fix"},
            code="pass",
            reasoning_obj=_make_reasoning_obj(),
            reasoning_validation=_ABSENT_VAL,
        )
        assert "eval_model_actual" in result
        assert "reasoning_correct" in result
        assert "mechanism_identified" in result
        assert "failure_type" in result
        assert "classify_raw" in result
        assert "classifier_mode" in result


# ============================================================
# Holdout integrity
# ============================================================


class TestHoldoutIntegrity:
    """Verify holdout, locked, and phase0 case sets don't overlap."""

    def test_no_overlap(self):
        holdout = json.load(open("reasoning_evaluator_audit/holdout_set.json"))
        locked = json.load(open("reasoning_evaluator_audit/locked_audit_set.json"))
        phase0 = json.load(open("reasoning_evaluator_audit/phase0_case_set.json"))

        h_ids = {c["case_id"] for c in holdout}
        l_ids = {c["case_id"] for c in locked}
        p_ids = {c["case_id"] for c in phase0}

        assert len(h_ids & l_ids) == 0, f"Holdout/locked overlap: {h_ids & l_ids}"
        assert len(h_ids & p_ids) == 0, f"Holdout/phase0 overlap: {h_ids & p_ids}"

    def test_exhaustive(self):
        holdout = json.load(open("reasoning_evaluator_audit/holdout_set.json"))
        locked = json.load(open("reasoning_evaluator_audit/locked_audit_set.json"))
        phase0 = json.load(open("reasoning_evaluator_audit/phase0_case_set.json"))
        cases = json.load(open("cases_v2.json"))

        all_audit = {c["case_id"] for c in holdout + locked + phase0}
        all_cases = {c["id"] for c in cases}
        assert all_audit == all_cases, f"Missing: {all_cases - all_audit}"

    def test_holdout_size(self):
        holdout = json.load(open("reasoning_evaluator_audit/holdout_set.json"))
        assert len(holdout) == 8

    def test_locked_size(self):
        locked = json.load(open("reasoning_evaluator_audit/locked_audit_set.json"))
        assert len(locked) == 30
