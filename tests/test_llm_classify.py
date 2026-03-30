"""Tests for the unified LLM classifier evaluation pipeline.

Validates:
  1. Evaluator coverage — runs on passing AND failing attempts
  2. Category correctness — all 4 quadrants (true_success, leg, lucky_fix, true_failure)
  3. No heuristic leakage — classifications come ONLY from LLM, not keywords
  4. Parsing robustness — malformed output fails explicitly
  5. Backward compatibility — pipeline runs end-to-end
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from evaluator import (
    compute_alignment,
    evaluate_output,
    llm_classify,
)
from reasoning import (
    parse_classify_output,
    compute_category,
    extract_reasoning_obj,
    validate_reasoning,
)

def _add_reasoning_fields(parsed, raw_json_str=None):
    """Add schema v2 reasoning_obj and reasoning_validation to a parsed dict."""
    raw_json = None
    if raw_json_str:
        raw_json = json.loads(raw_json_str)
    if raw_json and isinstance(raw_json, dict):
        parsed["reasoning_obj"] = extract_reasoning_obj(raw_json)
        parsed["reasoning_validation"] = validate_reasoning(parsed["reasoning_obj"], raw_json)
    else:
        parsed["reasoning_obj"] = extract_reasoning_obj({})
        parsed["reasoning_validation"] = validate_reasoning(parsed["reasoning_obj"], {})
    return parsed


# ============================================================
# 1. EVALUATOR COVERAGE — runs on both pass and fail
# ============================================================


def test_evaluator_runs_on_passing_attempt():
    """evaluate_output on passing code must still produce code_correct field."""
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    # Code that passes the conservation invariant
    raw = json.dumps(
        {
            "reasoning": "Transfer must conserve total balance.",
            "code": (
                "def transfer(a, b, amount):\n"
                "    a['balance'] -= amount\n"
                "    b['balance'] += amount\n"
            ),
        }
    )
    parsed = _add_reasoning_fields({
        "code": (
            "def transfer(a, b, amount):\n"
            "    a['balance'] -= amount\n"
            "    b['balance'] += amount\n"
        ),
        "reasoning": "Transfer must conserve total balance.",
        "raw_output": raw,
        "parse_error": None,
        "_raw_fallback": False,
    }, raw)
    result = evaluate_output(case, parsed)
    assert "code_correct" in result, "code_correct missing from passing attempt"
    assert "reasoning_correct" in result, "reasoning_correct missing from passing attempt"
    assert "alignment" in result
    assert "category" in result["alignment"]


def test_evaluator_runs_on_failing_attempt():
    """evaluate_output on failing code must still produce code_correct field."""
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    # Code that does NOT conserve balance (only debits)
    raw = json.dumps(
        {
            "reasoning": "Just debit the sender.",
            "code": "def transfer(a, b, amount):\n    a['balance'] -= amount\n",
        }
    )
    parsed = _add_reasoning_fields({
        "code": "def transfer(a, b, amount):\n    a['balance'] -= amount\n",
        "reasoning": "Just debit the sender.",
        "raw_output": raw,
        "parse_error": None,
        "_raw_fallback": False,
    }, raw)
    result = evaluate_output(case, parsed)
    assert "code_correct" in result, "code_correct missing from failing attempt"
    assert "reasoning_correct" in result, "reasoning_correct missing from failing attempt"
    assert "alignment" in result


# ============================================================
# 2. CATEGORY CORRECTNESS — all 4 quadrants
# ============================================================


def _cat(code_correct, reasoning_correct, reasoning_present=True, cpe=None, pf=False):
    """Shorthand for compute_category with schema v2 args."""
    return compute_category(code_correct, reasoning_correct, reasoning_present, cpe, pf)


def test_category_true_success():
    """reasoning_correct=True AND code_correct=True → true_success."""
    assert _cat(True, True) == "true_success"
    align = compute_alignment(True, True)
    assert align["category"] == "true_success"
    assert align["true_success"] is True
    assert align["leg_true"] is False
    assert align["lucky_fix"] is False
    assert align["true_failure"] is False


def test_category_leg():
    """reasoning_correct=True AND code_correct=False → leg."""
    assert _cat(False, True) == "leg"
    align = compute_alignment(False, True)
    assert align["category"] == "leg"
    assert align["leg_true"] is True
    assert align["true_success"] is False
    assert align["lucky_fix"] is False


def test_category_lucky_fix():
    """reasoning_correct=False AND code_correct=True → lucky_fix."""
    assert _cat(True, False) == "lucky_fix"
    align = compute_alignment(True, False)
    assert align["category"] == "lucky_fix"
    assert align["lucky_fix"] is True
    assert align["leg_true"] is False


def test_category_true_failure():
    """reasoning_correct=False AND code_correct=False → true_failure."""
    assert _cat(False, False) == "true_failure"
    align = compute_alignment(False, False)
    assert align["category"] == "true_failure"
    assert align["true_failure"] is True


def test_category_no_reasoning_and_parse_failed():
    """Schema v2 categories for no_reasoning and parse_failed."""
    assert _cat(True, None, reasoning_present=False) == "no_reasoning"
    assert _cat(True, None, reasoning_present=True, pf=True) == "parse_failed"
    assert _cat(True, None, reasoning_present=True) == "classifier_no_verdict"


# ============================================================
# 3. NO HEURISTIC LEAKAGE — LLM is sole source
# ============================================================


def test_evaluate_output_has_required_fields():
    """evaluate_output must populate code_correct (from exec) and reasoning_correct (from classifier)."""
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    raw = json.dumps(
        {
            "reasoning": "balance conservation.",
            "code": "def transfer(a, b, n): a['balance'] -= n; b['balance'] += n",
        }
    )
    parsed = _add_reasoning_fields({
        "code": "def transfer(a, b, n): a['balance'] -= n; b['balance'] += n",
        "reasoning": "balance conservation.",
        "raw_output": raw,
        "parse_error": None,
        "_raw_fallback": False,
    }, raw)
    result = evaluate_output(case, parsed)
    assert "code_correct" in result
    assert "reasoning_correct" in result
    assert "failure_type" in result
    assert "classify_parse_error" in result
    assert "category" in result["alignment"]


def test_code_correct_comes_from_exec_not_classifier():
    """code_correct MUST equal exec pass, regardless of classifier opinion."""
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    # Code that PASSES execution test
    passing_code = (
        "def transfer(a, b, amount):\n    a['balance'] -= amount\n    b['balance'] += amount"
    )
    parsed_pass = _add_reasoning_fields({
        "code": passing_code,
        "reasoning": "",
        "raw_output": passing_code,
        "parse_error": None,
        "_raw_fallback": False,
    })
    result_pass = evaluate_output(case, parsed_pass)
    assert result_pass["pass"] is True, "exec should pass"
    assert result_pass["code_correct"] is True, "code_correct must be True when exec passes"

    # Code that FAILS execution test
    failing_code = "def transfer(a, b, amount):\n    a['balance'] -= amount"
    parsed_fail = _add_reasoning_fields({
        "code": failing_code,
        "reasoning": "balance conservation.",
        "raw_output": failing_code,
        "parse_error": None,
        "_raw_fallback": False,
    })
    result_fail = evaluate_output(case, parsed_fail)
    assert result_fail["pass"] is False, "exec should fail"
    assert result_fail["code_correct"] is False, "code_correct must be False when exec fails"


def test_leg_uses_exec_not_classifier():
    """LEG must be: reasoning_correct AND NOT exec_pass."""
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    failing_code = "def transfer(a, b, amount):\n    a['balance'] -= amount"
    parsed = _add_reasoning_fields({
        "code": failing_code,
        "reasoning": "Must conserve total balance across accounts.",
        "raw_output": failing_code,
        "parse_error": None,
        "_raw_fallback": False,
    })
    result = evaluate_output(case, parsed)
    if result["reasoning_correct"] and not result["pass"]:
        assert result["alignment"]["category"] == "leg"


def test_classifier_template_has_no_exec_signals():
    """The classifier template must NOT contain execution results or pass/fail."""
    source = Path(__file__).resolve().parents[1] / "prompts" / "components" / "classify_reasoning.j2"
    text = source.read_text().lower()
    assert "exec_status" not in text, "Classifier template contains exec_status"
    assert "execution test result" not in text, "Classifier template contains execution results"
    assert "status: passed" not in text, "Classifier template contains pass/fail hint"
    assert "status: failed" not in text, "Classifier template contains pass/fail hint"
    assert "test_details" not in text, "Classifier template contains test details"


def test_no_keyword_matching_in_classification():
    """The classification must NOT depend on keyword matching.

    Verify that evaluate_output's code_correct and reasoning_correct
    are NOT computed by _detected_correct_reasoning (the heuristic).
    """
    source = Path(__file__).resolve().parents[1] / "evaluator.py"
    text = source.read_text()

    # The main evaluate_output function must NOT call _detected_correct_reasoning
    # for its classification decisions
    import ast

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_output":
            func_source = ast.get_source_segment(text, node)
            # reasoning_correct must come from classify result, not heuristic
            assert (
                "classify" in func_source
            ), "evaluate_output does not derive reasoning_correct from classifier"
            # _detected_correct_reasoning must NOT be called in evaluate_output
            assert "_detected_correct_reasoning" not in func_source, (
                "evaluate_output calls deprecated _detected_correct_reasoning"
            )
            break


# ============================================================
# 4. PARSING ROBUSTNESS
# ============================================================


def test_parse_valid_output():
    """Well-formed classifier output parses correctly (3-line, 5-field format)."""
    result = parse_classify_output("YES;YES;YES;YES;HIDDEN_DEPENDENCY\nHIGH\nCorrect reasoning.")
    assert result["mechanism_identified"] == "YES"
    assert result["invariant_identified"] == "YES"
    assert result["fix_alignment"] == "YES"
    assert result["reasoning_code_alignment"] == "YES"
    assert result["failure_type"] == "HIDDEN_DEPENDENCY"
    assert result["confidence"] == "HIGH"
    assert result["parse_error"] is None


def test_parse_no_mechanism():
    result = parse_classify_output("NO;NO;NO;NO;UNKNOWN\nLOW\nWrong mechanism.")
    assert result["mechanism_identified"] == "NO"
    assert result["failure_type"] == "UNKNOWN"
    assert result["confidence"] == "LOW"


def test_parse_empty_input():
    result = parse_classify_output("")
    assert result["parse_error"] is not None


def test_parse_too_few_lines():
    result = parse_classify_output("YES;YES;YES;YES;HIDDEN_DEPENDENCY")
    assert result["parse_error"] is not None
    assert "expected_3_lines" in result["parse_error"]


def test_parse_too_many_lines():
    result = parse_classify_output("YES;YES;YES;YES;HIDDEN_DEPENDENCY\nHIGH\nExplanation.\nExtra.")
    assert result["parse_error"] is not None
    assert "expected_3_lines" in result["parse_error"]


def test_parse_invalid_dimension():
    result = parse_classify_output("MAYBE;YES;YES;YES;HIDDEN_DEPENDENCY\nHIGH\nExplanation.")
    assert result["parse_error"] is not None
    assert "invalid_dimension" in result["parse_error"]


def test_parse_invalid_failure_type():
    """Unknown failure type is normalized to UNKNOWN, not a parse error."""
    result = parse_classify_output("YES;YES;YES;YES;MADE_UP_TYPE\nHIGH\nExplanation.")
    assert result["parse_error"] is None
    assert result["failure_type"] == "UNKNOWN"
    assert result["failure_type_raw"] == "MADE_UP_TYPE"


def test_parse_invalid_confidence():
    result = parse_classify_output("YES;YES;YES;YES;HIDDEN_DEPENDENCY\nMAYBE\nExplanation.")
    assert result["parse_error"] is not None
    assert "invalid_confidence" in result["parse_error"]


def test_parse_no_silent_defaults():
    """On parse failure, parse_error must be set."""
    result = parse_classify_output("GARBAGE")
    assert "parse_error" in result
    assert result["parse_error"] is not None
    assert "expected_3_lines" in result["parse_error"]


# ============================================================
# 5. BACKWARD COMPATIBILITY
# ============================================================


def test_full_pipeline_baseline():
    """Baseline condition runs end-to-end with new evaluator."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    cid, cond, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert "pass" in ev
    assert "score" in ev
    assert "alignment" in ev
    # New fields present
    assert "code_correct" in ev
    assert "reasoning_correct" in ev


def test_backward_compat_identified_correct_issue():
    """identified_correct_issue field still present for backward compat."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    _, _, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert "identified_correct_issue" in ev
    assert isinstance(ev["identified_correct_issue"], bool)


def test_backward_compat_reasoning_action_gap():
    """reasoning_action_gap field still present for backward compat."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    _, _, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert "reasoning_action_gap" in ev
    assert isinstance(ev["reasoning_action_gap"], bool)


def test_logging_includes_new_fields():
    """Log records must include the new classification fields."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="alias_config_a", cases_file="cases_v2.json")[0]
    _, _, ev = run_single(case, "gpt-4.1-nano", "baseline")
    # The eval dict is what gets logged
    assert "code_correct" in ev
    assert "reasoning_correct" in ev
    assert "failure_type" in ev
    assert "alignment" in ev
    assert "category" in ev["alignment"]
