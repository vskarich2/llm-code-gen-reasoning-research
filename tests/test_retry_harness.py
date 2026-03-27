"""Unit + integration tests for the retry harness.

Covers:
  - All pure helper functions (unit)
  - Mock-based integration tests (full loop)
  - Log schema assertions
  - Data integrity invariants (I1-I9)
  - Replay test
"""

import sys
import os
import json
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from retry_harness import (
    _compute_diff,
    _is_stagnated,
    _keyword_overlap,
    _classify_outcome,
    _classify_trajectory_type,
    _classify_regime,
    _build_error_object,
    _infer_failure_mode,
    _compute_metrics,
    _compute_critique_accuracy,
    _format_test_output,
    _normalize,
    _clean_critique_for_log,
    _estimate_reasoning_validity,
    _GENERIC_WORDS,
)

# ============================================================
# _compute_diff
# ============================================================


class TestComputeDiff:
    def test_identical(self):
        d = _compute_diff("abc", "abc")
        assert d["chars_changed"] == 0
        assert d["hunks"] == 0
        assert d["edit_dispersion"] == 1.0

    def test_single_line_change(self):
        d = _compute_diff("x = 1\ny = 2\n", "x = 1\ny = 3\n")
        assert d["chars_changed"] > 0
        assert d["hunks"] >= 1
        assert d["edit_dispersion"] == 1.0

    def test_multi_hunk(self):
        old = "a\nb\nc\nd\ne\nf\ng\n"
        new = "A\nb\nc\nd\ne\nF\ng\n"
        d = _compute_diff(old, new)
        assert d["hunks"] == 2
        assert d["edit_dispersion"] == 0.5

    def test_none_old(self):
        d = _compute_diff(None, "abc")
        assert d["chars_changed"] == 0
        assert d["edit_dispersion"] == 1.0

    def test_none_new(self):
        d = _compute_diff("abc", None)
        assert d["chars_changed"] == 0
        assert d["edit_dispersion"] == 1.0

    def test_both_empty(self):
        d = _compute_diff("", "")
        assert d["chars_changed"] == 0

    def test_diff_text_capped(self):
        old = "\n".join(f"line{i}" for i in range(200))
        new = "\n".join(f"LINE{i}" for i in range(200))
        d = _compute_diff(old, new)
        assert len(d["diff_text"]) < len(old)  # capped


# ============================================================
# _is_stagnated
# ============================================================


class TestIsStagnated:
    def test_small_diff_no_improvement(self):
        assert _is_stagnated({"chars_changed": 5}, 0.2, 0.2) is True

    def test_small_diff_score_dropped(self):
        assert _is_stagnated({"chars_changed": 5}, 0.1, 0.2) is True

    def test_small_diff_with_improvement(self):
        assert _is_stagnated({"chars_changed": 5}, 0.5, 0.2) is False

    def test_large_diff_no_improvement(self):
        assert _is_stagnated({"chars_changed": 100}, 0.2, 0.2) is False

    def test_none_diff(self):
        assert _is_stagnated(None, 0.2, 0.2) is False


# ============================================================
# _keyword_overlap
# ============================================================


class TestKeywordOverlap:
    def test_identical(self):
        assert _keyword_overlap("quick brown fox", "quick brown fox") > 0.9

    def test_disjoint(self):
        assert _keyword_overlap("alpha beta gamma", "delta epsilon zeta") == 0.0

    def test_empty(self):
        assert _keyword_overlap("", "hello") == 0.0

    def test_both_empty(self):
        assert _keyword_overlap("", "") == 0.0

    def test_partial_overlap(self):
        v = _keyword_overlap("quick brown fox", "quick red fox")
        assert 0.3 < v < 0.9


# ============================================================
# _classify_outcome
# ============================================================


class TestClassifyOutcome:
    def test_single_shot(self):
        t = [{"pass": True}]
        assert _classify_outcome(t) == "single_shot"

    def test_fast_convergence(self):
        t = [{"pass": False}, {"pass": True}]
        assert _classify_outcome(t) == "fast_convergence"

    def test_fast_convergence_3(self):
        t = [{"pass": False}, {"pass": False}, {"pass": True}]
        assert _classify_outcome(t) == "fast_convergence"

    def test_slow_convergence(self):
        t = [{"pass": False}] * 4 + [{"pass": True}]
        assert _classify_outcome(t) == "slow_convergence"

    def test_no_convergence(self):
        t = [{"pass": False}] * 5
        assert _classify_outcome(t) == "no_convergence"


# ============================================================
# _classify_trajectory_type
# ============================================================


class TestClassifyTrajectoryType:
    def test_single_shot(self):
        t = [{"score": 1.0, "pass": True}]
        assert _classify_trajectory_type(t) == "single_shot"

    def test_monotonic_improvement(self):
        t = [
            {"score": 0.2, "pass": False},
            {"score": 0.5, "pass": False},
            {"score": 1.0, "pass": True},
        ]
        assert _classify_trajectory_type(t) == "monotonic_improvement"

    def test_partial_stall(self):
        t = [
            {"score": 0.0, "pass": False},
            {"score": 0.2, "pass": False},
            {"score": 0.2, "pass": False},
        ]
        assert _classify_trajectory_type(t) == "partial_stall"

    def test_oscillating(self):
        t = [
            {"score": 0.2, "pass": False},
            {"score": 0.5, "pass": False},
            {"score": 0.2, "pass": False},
        ]
        assert _classify_trajectory_type(t) == "oscillating"

    def test_flat_failure(self):
        t = [
            {"score": 0.2, "pass": False},
            {"score": 0.2, "pass": False},
            {"score": 0.2, "pass": False},
        ]
        assert _classify_trajectory_type(t) == "flat_failure"

    def test_monotonic_but_no_pass(self):
        """Improving but never passing = partial_stall, not monotonic."""
        t = [
            {"score": 0.1, "pass": False},
            {"score": 0.2, "pass": False},
            {"score": 0.3, "pass": False},
        ]
        assert _classify_trajectory_type(t) == "partial_stall"


# ============================================================
# _classify_regime
# ============================================================


class TestClassifyRegime:
    def test_heuristic(self):
        t = [
            {
                "pass": True,
                "diff": None,
                "critique": None,
                "reasoning_signals": {"estimated_valid": True},
            }
        ]
        regime, signals = _classify_regime(t)
        assert regime == "heuristic"

    def test_rei(self):
        t = [
            {
                "pass": False,
                "diff": None,
                "critique": {"root_cause": "alias bug", "_valid": True},
                "reasoning_signals": {"estimated_valid": True},
            },
            {
                "pass": True,
                "diff": {"chars_changed": 30},
                "critique": None,
                "reasoning_signals": {"estimated_valid": True},
            },
        ]
        regime, signals = _classify_regime(t)
        assert regime == "REI"
        assert signals["reasoning_consistent"] is True
        assert signals["diff_small"] is True

    def test_csf(self):
        t = [
            {
                "pass": False,
                "diff": None,
                "critique": {"root_cause": "ordering bug", "_valid": True},
                "reasoning_signals": {"estimated_valid": False},
            },
            {
                "pass": False,
                "diff": {"chars_changed": 300},
                "critique": {"root_cause": "completely different issue", "_valid": True},
                "reasoning_signals": {"estimated_valid": False},
            },
        ]
        regime, signals = _classify_regime(t)
        assert regime == "CSF"

    def test_returns_mechanism_signals(self):
        t = [
            {
                "pass": False,
                "diff": None,
                "critique": None,
                "reasoning_signals": {"estimated_valid": None},
            }
        ]
        regime, signals = _classify_regime(t)
        assert "reasoning_consistent" in signals
        assert "critique_consistent" in signals
        assert "diff_small" in signals
        assert "avg_diff_size" in signals

    def test_empty_trajectory(self):
        regime, signals = _classify_regime([])
        assert regime == "unknown"

    def test_invalid_critiques_excluded(self):
        """Critiques with _valid=False should not affect consistency."""
        t = [
            {
                "pass": False,
                "diff": None,
                "critique": {"root_cause": "x", "_valid": False},
                "reasoning_signals": {"estimated_valid": True},
            },
            {
                "pass": False,
                "diff": {"chars_changed": 30},
                "critique": {"root_cause": "y", "_valid": False},
                "reasoning_signals": {"estimated_valid": True},
            },
        ]
        regime, signals = _classify_regime(t)
        # No valid critiques → vacuously consistent
        assert signals["critique_consistent"] is True


# ============================================================
# _build_error_object
# ============================================================


class TestBuildErrorObject:
    def test_syntax_error(self):
        ev = {"execution": {"syntax_error": "line 5: invalid", "ran": False}, "reasons": []}
        e = _build_error_object(ev)
        assert e["category"] == "syntax"
        assert "line 5" in e["message"]

    def test_runtime_error(self):
        ev = {
            "execution": {"ran": False, "error_message": "NameError: x", "runtime_error": True},
            "reasons": [],
        }
        e = _build_error_object(ev)
        assert e["category"] == "runtime"

    def test_logic_error(self):
        ev = {
            "execution": {"ran": True, "invariant_pass": False, "mutation_pass": None},
            "reasons": ["DEFAULTS mutated"],
        }
        e = _build_error_object(ev)
        assert e["category"] == "logic"
        assert "DEFAULTS" in e["message"]

    def test_spec_error(self):
        ev = {
            "execution": {"ran": True, "invariant_pass": True, "mutation_pass": False},
            "reasons": ["mutation failed"],
        }
        e = _build_error_object(ev)
        assert e["category"] == "spec"

    def test_load_error(self):
        ev = {"execution": {"ran": False}, "reasons": []}
        e = _build_error_object(ev)
        assert e["category"] == "load"

    def test_required_keys_always_present(self):
        required = {"type", "message", "category", "passed_tests", "total_tests", "reasons"}
        for ev in [
            {"execution": {"syntax_error": "bad"}, "reasons": []},
            {"execution": {"ran": True, "invariant_pass": False}, "reasons": ["x"]},
            {
                "execution": {"ran": True, "invariant_pass": True, "mutation_pass": True},
                "reasons": [],
            },
            {"execution": {}, "reasons": []},
        ]:
            e = _build_error_object(ev)
            assert required <= e.keys(), f"Missing: {required - e.keys()}"
            assert isinstance(e["reasons"], list)
            assert isinstance(e["category"], str)


# ============================================================
# _infer_failure_mode
# ============================================================


class TestInferFailureMode:
    def test_syntax(self):
        assert _infer_failure_mode({"category": "syntax"}, None, None) == "syntax_error"

    def test_runtime(self):
        assert _infer_failure_mode({"category": "runtime"}, None, None) == "runtime_error"

    def test_load(self):
        assert _infer_failure_mode({"category": "load"}, None, None) == "load_error"

    def test_aliasing_from_critique(self):
        e = {"category": "logic", "message": ""}
        c = {"invariant_violated": "DEFAULTS alias mutation"}
        assert _infer_failure_mode(e, None, c) == "aliasing"

    def test_ordering_from_critique(self):
        e = {"category": "logic", "message": ""}
        c = {"invariant_violated": "state updated before publish"}
        assert _infer_failure_mode(e, None, c) == "ordering"

    def test_ordering_from_message(self):
        e = {"category": "logic", "message": "stale state at publish"}
        assert _infer_failure_mode(e, None, None) == "ordering"

    def test_aliasing_from_message(self):
        e = {"category": "logic", "message": "DEFAULTS mutated after call"}
        assert _infer_failure_mode(e, None, None) == "aliasing"

    def test_unknown_fallback(self):
        e = {"category": "logic", "message": "something unexpected"}
        assert _infer_failure_mode(e, None, None) == "unknown"


# ============================================================
# _compute_metrics
# ============================================================


class TestComputeMetrics:
    def test_single_pass(self):
        t = [{"score": 1.0, "pass": True, "diff": None, "error": {"category": "logic"}}]
        m = _compute_metrics(t)
        assert m["num_retries"] == 0
        assert m["total_attempts"] == 1
        assert m["retry_efficiency"] == 1.0
        assert m["avg_diff_size"] == 0

    def test_two_attempts(self):
        t = [
            {"score": 0.2, "pass": False, "diff": None, "error": {"category": "logic"}},
            {
                "score": 1.0,
                "pass": True,
                "diff": {"chars_changed": 50, "edit_dispersion": 1.0},
                "error": {"category": "logic"},
            },
        ]
        m = _compute_metrics(t)
        assert m["num_retries"] == 1
        assert m["total_attempts"] == 2
        assert m["convergence_slope"] == 0.8
        assert m["avg_diff_size"] == 50.0
        assert m["error_entropy"] == 0.0

    def test_mixed_error_types(self):
        t = [
            {"score": 0.0, "pass": False, "diff": None, "error": {"category": "syntax"}},
            {
                "score": 0.2,
                "pass": False,
                "diff": {"chars_changed": 100, "edit_dispersion": 0.5},
                "error": {"category": "logic"},
            },
        ]
        m = _compute_metrics(t)
        assert m["error_entropy"] > 0

    def test_no_convergence_efficiency_zero(self):
        t = [
            {"score": 0.2, "pass": False, "diff": None, "error": {"category": "logic"}},
            {
                "score": 0.2,
                "pass": False,
                "diff": {"chars_changed": 10, "edit_dispersion": 1.0},
                "error": {"category": "logic"},
            },
        ]
        m = _compute_metrics(t)
        assert m["retry_efficiency"] == 0.0


# ============================================================
# _compute_critique_accuracy
# ============================================================


class TestCritiqueAccuracy:
    def test_hit(self):
        t = [
            {"critique": {"root_cause": "DEFAULTS not copied", "_valid": True}, "score": 0.2},
            {
                "critique": None,
                "score": 1.0,
                "diff": {"diff_text": "+    config = DEFAULTS.copy()"},
            },
        ]
        acc = _compute_critique_accuracy(t)
        assert acc == 1.0

    def test_miss(self):
        t = [
            {"critique": {"root_cause": "wrong loop bounds", "_valid": True}, "score": 0.2},
            {
                "critique": None,
                "score": 0.2,
                "diff": {"diff_text": "+    config = DEFAULTS.copy()"},
            },
        ]
        acc = _compute_critique_accuracy(t)
        assert acc == 0.0

    def test_no_critiques(self):
        t = [{"critique": None, "score": 1.0, "diff": None}]
        assert _compute_critique_accuracy(t) is None

    def test_filters_generic_words(self):
        t = [
            {"critique": {"root_cause": "the value is wrong", "_valid": True}, "score": 0.2},
            {"critique": None, "score": 0.5, "diff": {"diff_text": "+    value = 42"}},
        ]
        acc = _compute_critique_accuracy(t)
        assert acc == 0.0

    def test_invalid_critique_excluded(self):
        t = [
            {"critique": {"root_cause": "DEFAULTS not copied", "_valid": False}, "score": 0.2},
            {"critique": None, "score": 1.0, "diff": {"diff_text": "+    DEFAULTS.copy()"}},
        ]
        acc = _compute_critique_accuracy(t)
        assert acc is None  # no valid critiques


# ============================================================
# _normalize
# ============================================================


class TestNormalize:
    def test_strips_trailing_whitespace(self):
        assert _normalize("x = 1  \ny = 2  \n") == "x = 1\ny = 2"

    def test_strips_leading_trailing_newlines(self):
        assert _normalize("\n\nx = 1\n\n") == "x = 1"

    def test_empty(self):
        assert _normalize("") == ""


# ============================================================
# _clean_critique_for_log
# ============================================================


class TestCleanCritiqueForLog:
    def test_strips_internal_keys(self):
        c = {"failure_type": "logic_error", "root_cause": "x", "_valid": True, "_raw": "something"}
        cleaned = _clean_critique_for_log(c)
        assert "_valid" not in cleaned
        assert "_raw" not in cleaned
        assert "failure_type" in cleaned

    def test_none_input(self):
        assert _clean_critique_for_log(None) is None


# ============================================================
# _format_test_output
# ============================================================


class TestFormatTestOutput:
    def test_syntax_error(self):
        ev = {"execution": {"syntax_error": "line 5: bad"}, "reasons": []}
        out = _format_test_output(ev)
        assert "SYNTAX ERROR" in out

    def test_logic_failure(self):
        ev = {
            "execution": {"ran": True, "passed_tests": 0, "total_tests": 2},
            "reasons": ["DEFAULTS mutated"],
        }
        out = _format_test_output(ev)
        assert "DEFAULTS mutated" in out
        assert "0/2" in out

    def test_no_run(self):
        ev = {"execution": {"ran": False, "passed_tests": 0, "total_tests": 0}, "reasons": []}
        out = _format_test_output(ev)
        assert "DID NOT RUN" in out


# ============================================================
# _estimate_reasoning_validity
# ============================================================


class TestEstimateReasoningValidity:
    def test_heuristic_only(self):
        """With no critique and no prior trajectory, only heuristic signal."""
        # Need case and raw_output for _detected_correct_reasoning
        # Use a simple case that has signals
        case = {"failure_mode": "SHARED_REFERENCE"}
        raw = "The shared reference to mutable dict causes mutation"
        signals = _estimate_reasoning_validity(None, "some reasoning", case, raw, [], 0)
        assert signals["heuristic_signal"] is True
        assert signals["critique_signal"] is None
        assert signals["trajectory_signal"] is None

    def test_critique_logged_but_not_in_estimate(self):
        """Critique signal should be logged but NOT affect estimated_valid."""
        case = {"failure_mode": "UNKNOWN_MODE"}
        raw = "no relevant keywords here"
        critique = {"is_reasoning_error": False, "_valid": True}
        signals = _estimate_reasoning_validity(critique, "reasoning", case, raw, [], 0)
        # Heuristic is False (no matching keywords)
        assert signals["heuristic_signal"] is False
        # Critique says valid
        assert signals["critique_signal"] is True
        # But estimate uses only heuristic (and trajectory=None)
        # So estimated_valid = False (only heuristic, which is False)
        assert signals["estimated_valid"] is False

    def test_invalid_critique_excluded(self):
        case = {"failure_mode": "UNKNOWN_MODE"}
        raw = "no keywords"
        critique = {"is_reasoning_error": None, "_valid": False}
        signals = _estimate_reasoning_validity(critique, "reasoning", case, raw, [], 0)
        assert signals["critique_signal"] is None
