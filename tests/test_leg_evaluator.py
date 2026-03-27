"""Tests for leg_evaluator.py — strict parser, LEG computation, bias metric."""

import sys
import os
import inspect
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from leg_evaluator import (
    parse_evaluator_output,
    compute_leg_true,
    compute_reasoning_matches_truth,
    compute_evaluator_bias,
    FAILURE_TYPE_SET,
    _VALID_VERDICTS,
)
from failure_classifier import FAILURE_TYPES

# ============================================================
# PARSER — VALID INPUTS
# ============================================================


class TestParserValid:
    def test_yes_temporal(self):
        r = parse_evaluator_output("YES ; TEMPORAL_ORDERING")
        assert r["verdict"] == "YES"
        assert r["inferred_type"] == "TEMPORAL_ORDERING"
        assert r["parse_error"] is None

    def test_no_unknown(self):
        r = parse_evaluator_output("NO ; UNKNOWN")
        assert r["verdict"] == "NO"
        assert r["inferred_type"] == "UNKNOWN"

    def test_strips_whitespace(self):
        r = parse_evaluator_output("  YES  ;  HIDDEN_DEPENDENCY  ")
        assert r["verdict"] == "YES"
        assert r["inferred_type"] == "HIDDEN_DEPENDENCY"

    def test_allows_surrounding_blank_lines(self):
        r = parse_evaluator_output("\n  YES ; TEMPORAL_ORDERING  \n\n")
        assert r["verdict"] == "YES"
        assert r["inferred_type"] == "TEMPORAL_ORDERING"

    def test_all_failure_types(self):
        for ft in FAILURE_TYPES:
            r = parse_evaluator_output(f"NO ; {ft}")
            assert r["verdict"] == "NO"
            assert r["inferred_type"] == ft

    def test_raw_preserved(self):
        raw = "YES ; INVARIANT_VIOLATION"
        r = parse_evaluator_output(raw)
        assert r["raw"] == raw


# ============================================================
# PARSER — REJECTIONS (STRICT)
# ============================================================


class TestParserRejects:
    def test_rejects_partial(self):
        r = parse_evaluator_output("PARTIAL ; HIDDEN_DEPENDENCY")
        assert r["verdict"] is None
        assert "invalid_verdict" in r["parse_error"]

    def test_rejects_bad_type(self):
        r = parse_evaluator_output("YES ; WRONG_TYPE")
        assert r["verdict"] is None
        assert "invalid_type" in r["parse_error"]

    def test_rejects_no_semicolon(self):
        r = parse_evaluator_output("YES TEMPORAL_ORDERING")
        assert r["verdict"] is None
        assert "semicolon" in r["parse_error"]

    def test_rejects_empty(self):
        r = parse_evaluator_output("")
        assert r["verdict"] is None
        assert r["parse_error"] == "empty_response"

    def test_rejects_none(self):
        r = parse_evaluator_output(None)
        assert r["verdict"] is None

    def test_rejects_prose(self):
        r = parse_evaluator_output("The reasoning is correct because the model identified...")
        assert r["verdict"] is None

    def test_rejects_trailing_prose(self):
        r = parse_evaluator_output("YES ; TEMPORAL_ORDERING\nThis is because the ordering is wrong")
        assert r["verdict"] is None
        assert "extra_nonempty_lines" in r["parse_error"]

    def test_rejects_two_valid_lines(self):
        r = parse_evaluator_output("YES ; TEMPORAL_ORDERING\nNO ; HIDDEN_DEPENDENCY")
        assert r["verdict"] is None
        assert "extra_nonempty_lines" in r["parse_error"]

    def test_rejects_multiple_semicolons(self):
        r = parse_evaluator_output("YES ; TEMPORAL ; ORDERING")
        assert r["verdict"] is None
        assert "semicolon" in r["parse_error"]

    def test_rejects_empty_verdict(self):
        r = parse_evaluator_output(" ; TEMPORAL_ORDERING")
        assert r["verdict"] is None

    def test_rejects_type_not_in_enum(self):
        r = parse_evaluator_output("YES ; ORDERING_BUG")
        assert r["verdict"] is None


# ============================================================
# LEG_true
# ============================================================


class TestLegTrue:
    def test_match(self):
        e = {
            "pass": False,
            "llm_eval_blind_verdict": "YES",
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "TEMPORAL_ORDERING",
        }
        assert compute_leg_true(e) is True

    def test_type_mismatch(self):
        e = {
            "pass": False,
            "llm_eval_blind_verdict": "YES",
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "HIDDEN_DEPENDENCY",
        }
        assert compute_leg_true(e) is False

    def test_unknown_blocks(self):
        e = {
            "pass": False,
            "llm_eval_blind_verdict": "YES",
            "llm_eval_blind_type": "UNKNOWN",
            "classifier_failure_type": "UNKNOWN",
        }
        assert compute_leg_true(e) is False

    def test_verdict_no(self):
        e = {
            "pass": False,
            "llm_eval_blind_verdict": "NO",
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "TEMPORAL_ORDERING",
        }
        assert compute_leg_true(e) is False

    def test_pass_blocks(self):
        e = {
            "pass": True,
            "llm_eval_blind_verdict": "YES",
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "TEMPORAL_ORDERING",
        }
        assert compute_leg_true(e) is False

    def test_none_verdict(self):
        e = {
            "pass": False,
            "llm_eval_blind_verdict": None,
            "llm_eval_blind_type": None,
            "classifier_failure_type": "TEMPORAL_ORDERING",
        }
        assert compute_leg_true(e) is False

    def test_missing_classifier(self):
        e = {
            "pass": False,
            "llm_eval_blind_verdict": "YES",
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
        }
        assert compute_leg_true(e) is False

    def test_missing_pass_defaults_true(self):
        """If pass key missing, defaults to True via .get(pass, True) → not LEG."""
        e = {
            "llm_eval_blind_verdict": "YES",
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "TEMPORAL_ORDERING",
        }
        assert compute_leg_true(e) is False


# ============================================================
# reasoning_matches_truth
# ============================================================


class TestReasoningMatchesTruth:
    def test_match(self):
        e = {
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "TEMPORAL_ORDERING",
        }
        assert compute_reasoning_matches_truth(e) is True

    def test_mismatch(self):
        e = {
            "llm_eval_blind_type": "TEMPORAL_ORDERING",
            "classifier_failure_type": "HIDDEN_DEPENDENCY",
        }
        assert compute_reasoning_matches_truth(e) is False

    def test_unknown(self):
        e = {"llm_eval_blind_type": "UNKNOWN", "classifier_failure_type": "TEMPORAL_ORDERING"}
        assert compute_reasoning_matches_truth(e) is False

    def test_none(self):
        e = {"llm_eval_blind_type": None, "classifier_failure_type": "X"}
        assert compute_reasoning_matches_truth(e) is False


# ============================================================
# EVALUATOR BIAS
# ============================================================


class TestEvaluatorBias:
    def test_no_bias(self):
        traj = [
            {"llm_eval_blind_verdict": "YES", "llm_eval_conditioned_verdict": "YES"},
            {"llm_eval_blind_verdict": "NO", "llm_eval_conditioned_verdict": "NO"},
        ]
        b = compute_evaluator_bias(traj)
        assert b["bias_rate_relative"] == 0.0
        assert b["bias_rate_absolute"] == 0.0

    def test_positive_bias(self):
        traj = [
            {"llm_eval_blind_verdict": "YES", "llm_eval_conditioned_verdict": "YES"},
            {"llm_eval_blind_verdict": "NO", "llm_eval_conditioned_verdict": "YES"},
        ]
        b = compute_evaluator_bias(traj)
        assert b["blind_yes"] == 1
        assert b["conditioned_yes"] == 2
        assert b["bias_rate_relative"] == 1.0  # 100% inflation

    def test_zero_blind_yes(self):
        traj = [
            {"llm_eval_blind_verdict": "NO", "llm_eval_conditioned_verdict": "YES"},
        ]
        b = compute_evaluator_bias(traj)
        assert b["bias_rate_relative"] is None

    def test_skips_none(self):
        traj = [
            {"llm_eval_blind_verdict": None, "llm_eval_conditioned_verdict": "YES"},
            {"llm_eval_blind_verdict": "YES", "llm_eval_conditioned_verdict": "YES"},
        ]
        b = compute_evaluator_bias(traj)
        assert b["total_evaluated"] == 1


# ============================================================
# INVARIANT TESTS
# ============================================================


class TestInvariants:
    def test_no_heuristic_in_leg_true(self):
        source = inspect.getsource(compute_leg_true)
        for word in [
            "keyword",
            "latent_signal",
            "detect_failure_type_from_reasoning",
            "regex",
            "fuzzy",
            "embedding",
            "similarity",
            "ontology",
            "alignment",
            "conditioned",
        ]:
            assert word not in source.lower(), f"forbidden: '{word}' in compute_leg_true"

    def test_enum_complete(self):
        assert len(FAILURE_TYPES) == 9  # 8 specific + UNKNOWN (+ CONFOUNDING_LOGIC)
        assert "UNKNOWN" in FAILURE_TYPE_SET
        for ft in FAILURE_TYPES:
            assert ft == ft.upper()
            assert " " not in ft

    def test_verdict_enum(self):
        assert _VALID_VERDICTS == frozenset(["YES", "NO"])
        assert "PARTIAL" not in _VALID_VERDICTS
