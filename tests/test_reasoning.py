"""Tests for reasoning pipeline — schema, validation, classification, categories."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reasoning import (
    extract_reasoning_obj,
    validate_reasoning,
    parse_classify_output,
    compute_reasoning_correct,
    compute_category,
    REQUIRED_REASONING_FIELDS,
    COVERED_CATEGORIES,
    NULL_CLASSIFIER_RESULT,
    DEBUG_DELIMITER,
    CLASSIFIER_DIMENSIONS,
)


# ============================================================
# EXTRACTION
# ============================================================

class TestExtraction:

    def test_all_fields_present(self):
        raw = {"root_cause": "rc", "failure_mechanism": "fm",
               "broken_invariant": "bi", "fix_strategy": "fs", "files": {}}
        obj = extract_reasoning_obj(raw)
        assert obj["root_cause"] == "rc"
        assert obj["failure_mechanism"] == "fm"
        assert obj["broken_invariant"] == "bi"
        assert obj["fix_strategy"] == "fs"

    def test_missing_fields_default_empty(self):
        obj = extract_reasoning_obj({"files": {}})
        for f in REQUIRED_REASONING_FIELDS:
            assert obj[f] == ""

    def test_leg_fields_string_self_check(self):
        raw = {"root_cause": "rc", "failure_mechanism": "fm",
               "broken_invariant": "bi", "fix_strategy": "fs",
               "self_check": "checked invariant holds",
               "alternative_hypothesis": "could be threading",
               "hypothesis_rejection": "no threads in code"}
        obj = extract_reasoning_obj(raw)
        assert obj["self_check"] == "checked invariant holds"
        assert obj["alternative_hypothesis"] == "could be threading"
        assert obj["hypothesis_rejection"] == "no threads in code"

    def test_leg_fields_dict_self_check(self):
        raw = {"root_cause": "rc", "failure_mechanism": "fm",
               "broken_invariant": "bi", "fix_strategy": "fs",
               "self_check": {
                   "failure_scenario": "concurrent access",
                   "edge_case": "empty input",
                   "invariant_check": "holds under retry",
                   "conclusion": "safe"
               },
               "alternative_hypothesis": "race condition",
               "hypothesis_rejection": "single-threaded"}
        obj = extract_reasoning_obj(raw)
        assert isinstance(obj["self_check"], dict)
        assert obj["self_check"]["failure_scenario"] == "concurrent access"
        assert obj["self_check"]["conclusion"] == "safe"
        assert obj["alternative_hypothesis"] == "race condition"


# ============================================================
# VALIDATION
# ============================================================

class TestValidation:

    def test_no_fields_in_json(self):
        obj = extract_reasoning_obj({"code": "x"})
        v = validate_reasoning(obj, {"code": "x"})
        assert v["reasoning_attempted"] == False
        assert v["reasoning_present"] == False

    def test_partial_fields_in_json(self):
        raw = {"root_cause": "something long enough to pass", "code": "x"}
        obj = extract_reasoning_obj(raw)
        v = validate_reasoning(obj, raw)
        assert v["reasoning_attempted"] == False  # not ALL fields in json
        assert v["reasoning_present"] == False  # not ALL fields have content

    def test_all_fields_empty(self):
        raw = {"root_cause": "", "failure_mechanism": "", "broken_invariant": "", "fix_strategy": ""}
        obj = extract_reasoning_obj(raw)
        v = validate_reasoning(obj, raw)
        assert v["reasoning_attempted"] == True
        assert v["reasoning_present"] == False

    def test_all_fields_populated(self):
        raw = {f: "x" * 20 for f in REQUIRED_REASONING_FIELDS}
        obj = extract_reasoning_obj(raw)
        v = validate_reasoning(obj, raw)
        assert v["reasoning_attempted"] == True
        assert v["reasoning_present"] == True

    def test_one_field_too_short(self):
        raw = {f: "x" * 20 for f in REQUIRED_REASONING_FIELDS}
        raw["broken_invariant"] = "short"  # < 10 chars
        obj = extract_reasoning_obj(raw)
        v = validate_reasoning(obj, raw)
        assert v["reasoning_attempted"] == True
        assert v["reasoning_present"] == False  # ALL must pass

    def test_lengths_structured(self):
        raw = {"root_cause": "abc", "failure_mechanism": "defgh" * 5,
               "broken_invariant": "", "fix_strategy": "x" * 100}
        obj = extract_reasoning_obj(raw)
        v = validate_reasoning(obj, raw)
        lengths = v["reasoning_lengths"]
        assert lengths["root_cause"]["length"] == 3
        assert lengths["root_cause"]["present"] == False
        assert lengths["failure_mechanism"]["length"] == 25
        assert lengths["failure_mechanism"]["present"] == True
        assert lengths["broken_invariant"]["length"] == 0
        assert lengths["broken_invariant"]["present"] == False


# ============================================================
# CLASSIFIER OUTPUT PARSING (5-line, 6-field, dual-channel)
# ============================================================

def _make_output(dims="CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY",
                 conf="HIGH",
                 counter="Counterfactual: Removing the cause eliminates the bug.",
                 evidence="Evidence: config = DEFAULTS creates alias; .update() mutates global.",
                 judgment="Judgment: Reasoning correctly identifies aliasing."):
    """Helper to build valid 5-line classifier output."""
    return f"{dims}\n{conf}\n{counter}\n{evidence}\n{judgment}"


class TestClassifierParsing:

    def test_valid_5_lines(self):
        raw = _make_output()
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["mechanism_identified"] == "CORRECT"
        assert r["invariant_identified"] == "CORRECT"
        assert r["causal_chain_complete"] == "CORRECT"
        assert r["fix_alignment"] == "CORRECT"
        assert r["reasoning_code_alignment"] == "CORRECT"
        assert r["failure_type"] == "HIDDEN_DEPENDENCY"
        assert r["confidence"] == "HIGH"
        assert "Counterfactual" in r["counterfactual"]
        assert "Evidence" in r["evidence"]
        assert "Judgment" in r["judgment"]
        # Legacy alias
        assert r["explanation"] == r["judgment"]

    def test_whitespace_normalization(self):
        raw = " CORRECT ; CORRECT ; CORRECT ; CORRECT ; CORRECT ; HIDDEN_DEPENDENCY \n HIGH \n Counterfactual: x \n Evidence: y \n Judgment: z "
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["mechanism_identified"] == "CORRECT"
        assert r["confidence"] == "HIGH"

    def test_lowercase_normalization(self):
        raw = _make_output(dims="correct;correct;correct;correct;correct;hidden_dependency",
                           conf="high")
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["mechanism_identified"] == "CORRECT"
        assert r["confidence"] == "HIGH"
        assert r["failure_type"] == "HIDDEN_DEPENDENCY"

    def test_too_few_lines(self):
        r = parse_classify_output("CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY")
        assert r["parse_error"] == "expected_5_lines_got_1"

    def test_too_many_lines_without_debug(self):
        raw = _make_output() + "\nExtra line."
        r = parse_classify_output(raw)
        assert r["parse_error"] == "expected_5_lines_got_6"

    def test_too_few_fields(self):
        raw = _make_output(dims="CORRECT;CORRECT;CORRECT")
        r = parse_classify_output(raw)
        assert r["parse_error"] == "expected_6_fields_got_3"

    def test_invalid_dimension(self):
        raw = _make_output(dims="MAYBE;CORRECT;CORRECT;CORRECT;CORRECT;HIDDEN_DEPENDENCY")
        r = parse_classify_output(raw)
        assert "invalid_dimension" in r["parse_error"]

    def test_invalid_confidence(self):
        raw = _make_output(conf="MAYBE")
        r = parse_classify_output(raw)
        assert "invalid_confidence" in r["parse_error"]

    def test_missing_judgment(self):
        raw = _make_output(judgment="   ")
        r = parse_classify_output(raw)
        # Whitespace-only judgment line is filtered → only 4 lines
        assert "expected_5_lines_got_4" in r["parse_error"]

    def test_unknown_failure_type(self):
        raw = _make_output(dims="CORRECT;CORRECT;CORRECT;CORRECT;CORRECT;TYPO_TYPE")
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["failure_type"] == "UNKNOWN"
        assert r["failure_type_raw"] == "TYPO_TYPE"

    def test_partial_and_wrong_dimensions(self):
        raw = _make_output(dims="PARTIAL;WRONG;PARTIAL;WRONG;PARTIAL;UNKNOWN",
                           conf="LOW")
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["mechanism_identified"] == "PARTIAL"
        assert r["invariant_identified"] == "WRONG"
        assert r["causal_chain_complete"] == "PARTIAL"
        assert r["fix_alignment"] == "WRONG"
        assert r["reasoning_code_alignment"] == "PARTIAL"
        assert r["confidence"] == "LOW"

    # --- DEBUG SECTION TESTS ---

    def test_debug_section_ignored(self):
        """Debug section after delimiter must not affect parsing."""
        raw = _make_output() + "\n---DEBUG---\nThis is debug text.\nMore debug.\nEven more."
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["mechanism_identified"] == "CORRECT"
        assert r["confidence"] == "HIGH"

    def test_debug_section_with_extra_lines(self):
        """Debug section can have any number of lines."""
        debug = "\n".join([f"Debug line {i}" for i in range(20)])
        raw = _make_output() + f"\n---DEBUG---\n{debug}"
        r = parse_classify_output(raw)
        assert r["parse_error"] is None

    def test_debug_section_empty(self):
        """Debug delimiter with no content after it."""
        raw = _make_output() + "\n---DEBUG---"
        r = parse_classify_output(raw)
        assert r["parse_error"] is None

    def test_no_debug_section(self):
        """Output without debug section parses normally."""
        raw = _make_output()
        r = parse_classify_output(raw)
        assert r["parse_error"] is None

    def test_debug_does_not_affect_metrics(self):
        """Identical outputs with and without debug produce same dimensions."""
        raw_no_debug = _make_output(dims="PARTIAL;CORRECT;WRONG;CORRECT;PARTIAL;UNKNOWN")
        raw_with_debug = raw_no_debug + "\n---DEBUG---\nSome analysis here."
        r1 = parse_classify_output(raw_no_debug)
        r2 = parse_classify_output(raw_with_debug)
        for k in ["mechanism_identified", "invariant_identified", "causal_chain_complete",
                   "fix_alignment", "reasoning_code_alignment", "failure_type", "confidence"]:
            assert r1[k] == r2[k], f"Mismatch on {k}: {r1[k]} vs {r2[k]}"

    def test_malformed_debug_does_not_break_parsing(self):
        """Garbage in debug section must not affect the first 5 lines."""
        raw = _make_output() + "\n---DEBUG---\n{{{invalid json\n\x00\x01\x02binary garbage"
        r = parse_classify_output(raw)
        assert r["parse_error"] is None
        assert r["mechanism_identified"] == "CORRECT"


# ============================================================
# REASONING_CORRECT DERIVATION
# ============================================================

class TestReasoningCorrect:

    def test_strict_all_correct(self):
        dims = {"mechanism_identified": "CORRECT", "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "strict") == True

    def test_strict_mechanism_partial(self):
        dims = {"mechanism_identified": "PARTIAL", "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "strict") == False

    def test_strict_invariant_partial(self):
        dims = {"mechanism_identified": "CORRECT", "invariant_identified": "PARTIAL",
                "causal_chain_complete": "CORRECT", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "strict") == True

    def test_strict_causal_chain_partial(self):
        dims = {"mechanism_identified": "CORRECT", "invariant_identified": "CORRECT",
                "causal_chain_complete": "PARTIAL", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "strict") == True

    def test_strict_fix_wrong(self):
        dims = {"mechanism_identified": "CORRECT", "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT", "fix_alignment": "WRONG"}
        assert compute_reasoning_correct(dims, "strict") == False

    def test_lenient_mechanism_partial(self):
        dims = {"mechanism_identified": "PARTIAL", "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "lenient") == True

    def test_raw_returns_none(self):
        dims = {"mechanism_identified": "CORRECT", "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "raw") is None

    def test_none_dimension(self):
        dims = {"mechanism_identified": None, "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT", "fix_alignment": "CORRECT"}
        assert compute_reasoning_correct(dims, "strict") is None


# ============================================================
# CATEGORY COMPUTATION
# ============================================================

class TestCategory:

    def test_true_success(self):
        assert compute_category(True, True, True, None, False) == "true_success"

    def test_leg(self):
        assert compute_category(False, True, True, None, False) == "leg"

    def test_lucky_fix(self):
        assert compute_category(True, False, True, None, False) == "lucky_fix"

    def test_true_failure(self):
        assert compute_category(False, False, True, None, False) == "true_failure"

    def test_no_reasoning(self):
        assert compute_category(True, None, False, None, False) == "no_reasoning"

    def test_classifier_parse_failed(self):
        assert compute_category(True, None, True, "expected_5_lines_got_3", False) == "classifier_parse_failed"

    def test_classifier_no_verdict(self):
        assert compute_category(True, None, True, None, False) == "classifier_no_verdict"

    def test_parse_failed(self):
        assert compute_category(None, None, False, None, True) == "parse_failed"

    def test_coverage_includes_only_covered(self):
        covered = {"true_success", "leg", "lucky_fix", "true_failure"}
        not_covered = {"no_reasoning", "classifier_parse_failed", "classifier_no_verdict", "parse_failed"}
        assert covered == COVERED_CATEGORIES
        for cat in not_covered:
            assert cat not in COVERED_CATEGORIES


# ============================================================
# ADVERSARIAL
# ============================================================

class TestAdversarial:

    def test_correct_reasoning_wrong_code(self):
        """LEG regime: reasoning correct but code fails."""
        dims = {"mechanism_identified": "CORRECT", "invariant_identified": "CORRECT",
                "causal_chain_complete": "CORRECT",
                "fix_alignment": "CORRECT", "reasoning_code_alignment": "WRONG"}
        rc = compute_reasoning_correct(dims, "strict")
        assert rc == True
        cat = compute_category(code_correct=False, reasoning_correct=rc,
                               reasoning_present=True, classifier_parse_error=None, parse_failed=False)
        assert cat == "leg"

    def test_wrong_reasoning_correct_code(self):
        """Lucky fix: code works but reasoning is wrong."""
        dims = {"mechanism_identified": "WRONG", "invariant_identified": "WRONG",
                "causal_chain_complete": "WRONG",
                "fix_alignment": "WRONG", "reasoning_code_alignment": "PARTIAL"}
        rc = compute_reasoning_correct(dims, "strict")
        assert rc == False
        cat = compute_category(code_correct=True, reasoning_correct=rc,
                               reasoning_present=True, classifier_parse_error=None, parse_failed=False)
        assert cat == "lucky_fix"

    def test_correct_invariant_wrong_mechanism(self):
        """Right invariant, wrong mechanism → reasoning incorrect."""
        dims = {"mechanism_identified": "WRONG", "invariant_identified": "CORRECT",
                "causal_chain_complete": "WRONG",
                "fix_alignment": "WRONG", "reasoning_code_alignment": "WRONG"}
        rc = compute_reasoning_correct(dims, "strict")
        assert rc == False  # mechanism WRONG → reasoning incorrect

    def test_missing_reasoning_excluded(self):
        cat = compute_category(code_correct=True, reasoning_correct=None,
                               reasoning_present=False, classifier_parse_error=None, parse_failed=False)
        assert cat == "no_reasoning"
        assert cat not in COVERED_CATEGORIES


# ============================================================
# CONSTANTS
# ============================================================

class TestConstants:

    def test_classifier_dimensions_count(self):
        assert len(CLASSIFIER_DIMENSIONS) == 5

    def test_null_classifier_has_all_dimensions(self):
        for d in CLASSIFIER_DIMENSIONS:
            assert d in NULL_CLASSIFIER_RESULT
        assert "causal_chain_complete" in NULL_CLASSIFIER_RESULT
        assert "counterfactual" in NULL_CLASSIFIER_RESULT
        assert "evidence" in NULL_CLASSIFIER_RESULT
        assert "judgment" in NULL_CLASSIFIER_RESULT

    def test_debug_delimiter(self):
        assert DEBUG_DELIMITER == "---DEBUG---"
