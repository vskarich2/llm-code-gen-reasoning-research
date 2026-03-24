"""Tests for failure_classifier.py.

All tests use synthetic data only. NO case metadata (case_id, failure_mode).
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from failure_classifier import classify_failure, FAILURE_TYPES


class TestRule1CritiqueKeywords:
    def test_temporal_from_ordering_keywords(self):
        critique = {"failure_type": "logic_error",
                    "root_cause": "state read before write",
                    "invariant_violated": "ordering constraint", "_valid": True}
        error = {"category": "logic", "message": "", "reasons": []}
        r = classify_failure(error, critique)
        assert r["failure_type_final"] == "TEMPORAL_ORDERING"
        assert r["classifier_confidence"] == 0.8
        assert r["classifier_rule_path"] == "rule1_critique_keyword"

    def test_hidden_dep_from_missing(self):
        critique = {"failure_type": "logic_error",
                    "root_cause": "function not defined in scope",
                    "invariant_violated": "hidden dependency", "_valid": True}
        error = {"category": "logic", "message": "", "reasons": []}
        r = classify_failure(error, critique)
        assert r["failure_type_final"] == "HIDDEN_DEPENDENCY"

    def test_invariant_from_conservation(self):
        critique = {"failure_type": "logic_error",
                    "root_cause": "balance not conserved",
                    "invariant_violated": "conservation law", "_valid": True}
        error = {"category": "logic", "message": "", "reasons": []}
        r = classify_failure(error, critique)
        assert r["failure_type_final"] == "INVARIANT_VIOLATION"

    def test_retry_from_duplicate(self):
        critique = {"failure_type": "logic_error",
                    "root_cause": "job sent twice on retry",
                    "invariant_violated": "idempotency", "_valid": True}
        error = {"category": "logic", "message": "", "reasons": []}
        r = classify_failure(error, critique)
        assert r["failure_type_final"] == "RETRY_LOGIC_BUG"

    def test_invalid_critique_skipped(self):
        critique = {"failure_type": "unknown", "root_cause": "ordering issue",
                    "invariant_violated": "", "_valid": False}
        error = {"category": "logic", "message": "stale state", "reasons": ["stale state"]}
        r = classify_failure(error, critique)
        # Should NOT use critique (invalid), should fall through to rule 3
        assert r["classifier_rule_path"] != "rule1_critique_keyword"


class TestRule2ErrorCategory:
    def test_syntax_maps_to_edge_case(self):
        r = classify_failure({"category": "syntax", "message": "line 5", "reasons": []}, None)
        assert r["failure_type_final"] == "EDGE_CASE_MISSED"
        assert r["classifier_confidence"] == 0.5

    def test_load_maps_to_hidden_dep(self):
        r = classify_failure({"category": "load", "message": "", "reasons": []}, None)
        assert r["failure_type_final"] == "HIDDEN_DEPENDENCY"

    def test_runtime_nameerror(self):
        r = classify_failure(
            {"category": "runtime", "message": "NameError: name 'foo' is not defined", "reasons": []},
            None)
        assert r["failure_type_final"] == "HIDDEN_DEPENDENCY"
        assert "NameError" in r["matched_keywords"]

    def test_runtime_keyerror(self):
        r = classify_failure(
            {"category": "runtime", "message": "KeyError: 'balance'", "reasons": []}, None)
        assert r["failure_type_final"] == "PARTIAL_STATE_UPDATE"

    def test_runtime_unknown(self):
        r = classify_failure(
            {"category": "runtime", "message": "ZeroDivisionError", "reasons": []}, None)
        assert r["failure_type_final"] == "CONFOUNDING_LOGIC"


class TestRule3ReasonKeywords:
    def test_ordering_from_reasons(self):
        r = classify_failure(
            {"category": "logic", "message": "", "reasons": ["stale state at publish"]}, None)
        assert r["failure_type_final"] == "TEMPORAL_ORDERING"
        assert r["classifier_confidence"] == 0.3

    def test_duplicate_from_reasons(self):
        r = classify_failure(
            {"category": "logic", "message": "", "reasons": ["duplicate emails sent"]}, None)
        assert r["failure_type_final"] == "RETRY_LOGIC_BUG"


class TestRule4Fallback:
    def test_unknown_when_no_signals(self):
        r = classify_failure(
            {"category": "logic", "message": "test failed", "reasons": ["test failed"]}, None)
        assert r["failure_type_final"] == "UNKNOWN"
        assert r["classifier_confidence"] == 0.0
        assert r["classifier_rule_path"] == "rule4_fallback"

    def test_empty_error(self):
        r = classify_failure({"category": "", "message": "", "reasons": []}, None)
        assert r["failure_type_final"] == "UNKNOWN"


class TestInvariants:
    def test_never_returns_null_fields(self):
        for error in [
            {"category": "logic", "message": "", "reasons": []},
            {"category": "", "message": "", "reasons": []},
            {"category": "syntax", "message": "bad", "reasons": ["x"]},
        ]:
            for critique in [None, {"_valid": False}, {"_valid": True, "root_cause": "x", "invariant_violated": ""}]:
                r = classify_failure(error, critique)
                assert r["failure_type_final"] is not None
                assert r["failure_type_final"] in FAILURE_TYPES
                assert r["classifier_rule_path"] is not None
                assert isinstance(r["classifier_confidence"], (int, float))
                assert isinstance(r["matched_keywords"], list)

    def test_no_case_parameter(self):
        """Classifier signature must NOT accept case metadata."""
        import inspect
        sig = inspect.signature(classify_failure)
        params = list(sig.parameters.keys())
        assert "case" not in params
        assert "case_id" not in params
        assert "failure_mode" not in params
