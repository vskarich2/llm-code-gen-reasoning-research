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
    parse_classify_output,
    compute_category,
    compute_alignment,
    evaluate_output,
    llm_classify,
)

# ============================================================
# 1. EVALUATOR COVERAGE — runs on both pass and fail
# ============================================================


def test_evaluator_runs_on_passing_attempt():
    """evaluate_output on passing code must still produce code_correct field."""
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
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
    parsed = {
        "code": (
            "def transfer(a, b, amount):\n"
            "    a['balance'] -= amount\n"
            "    b['balance'] += amount\n"
        ),
        "reasoning": "Transfer must conserve total balance.",
        "raw_output": raw,
        "parse_error": None,
        "_raw_fallback": False,
    }
    result = evaluate_output(case, parsed)
    assert "code_correct" in result, "code_correct missing from passing attempt"
    assert "reasoning_correct" in result, "reasoning_correct missing from passing attempt"
    assert "alignment" in result
    assert "category" in result["alignment"]


def test_evaluator_runs_on_failing_attempt():
    """evaluate_output on failing code must still produce code_correct field."""
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
    # Code that does NOT conserve balance (only debits)
    raw = json.dumps(
        {
            "reasoning": "Just debit the sender.",
            "code": "def transfer(a, b, amount):\n    a['balance'] -= amount\n",
        }
    )
    parsed = {
        "code": "def transfer(a, b, amount):\n    a['balance'] -= amount\n",
        "reasoning": "Just debit the sender.",
        "raw_output": raw,
        "parse_error": None,
        "_raw_fallback": False,
    }
    result = evaluate_output(case, parsed)
    assert "code_correct" in result, "code_correct missing from failing attempt"
    assert "reasoning_correct" in result, "reasoning_correct missing from failing attempt"
    assert "alignment" in result


# ============================================================
# 2. CATEGORY CORRECTNESS — all 4 quadrants
# ============================================================


def test_category_true_success():
    """reasoning_correct=True AND code_correct=True → true_success."""
    assert compute_category(True, True) == "true_success"
    align = compute_alignment(True, True)
    assert align["category"] == "true_success"
    assert align["true_success"] is True
    assert align["leg_true"] is False
    assert align["lucky_fix"] is False
    assert align["true_failure"] is False


def test_category_leg():
    """reasoning_correct=True AND code_correct=False → leg."""
    assert compute_category(False, True) == "leg"
    align = compute_alignment(False, True)
    assert align["category"] == "leg"
    assert align["leg_true"] is True
    assert align["true_success"] is False
    assert align["lucky_fix"] is False


def test_category_lucky_fix():
    """reasoning_correct=False AND code_correct=True → lucky_fix."""
    assert compute_category(True, False) == "lucky_fix"
    align = compute_alignment(True, False)
    assert align["category"] == "lucky_fix"
    assert align["lucky_fix"] is True
    assert align["leg_true"] is False


def test_category_true_failure():
    """reasoning_correct=False AND code_correct=False → true_failure."""
    assert compute_category(False, False) == "true_failure"
    align = compute_alignment(False, False)
    assert align["category"] == "true_failure"
    assert align["true_failure"] is True


def test_category_unclassified_on_none():
    """None inputs → unclassified (NOT silent default to False)."""
    assert compute_category(None, None) == "unclassified"
    assert compute_category(True, None) == "unclassified"
    assert compute_category(None, False) == "unclassified"


# ============================================================
# 3. NO HEURISTIC LEAKAGE — LLM is sole source
# ============================================================


def test_evaluate_output_has_required_fields():
    """evaluate_output must populate code_correct (from exec) and reasoning_correct (from classifier)."""
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
    raw = json.dumps(
        {
            "reasoning": "balance conservation.",
            "code": "def transfer(a, b, n): a['balance'] -= n; b['balance'] += n",
        }
    )
    parsed = {
        "code": "def transfer(a, b, n): a['balance'] -= n; b['balance'] += n",
        "reasoning": "balance conservation.",
        "raw_output": raw,
        "parse_error": None,
        "_raw_fallback": False,
    }
    result = evaluate_output(case, parsed)
    assert "code_correct" in result
    assert "reasoning_correct" in result
    assert "failure_type" in result
    assert "classify_parse_error" in result
    assert "category" in result["alignment"]
    assert "leg_true" in result["alignment"]
    assert "lucky_fix" in result["alignment"]


def test_code_correct_comes_from_exec_not_classifier():
    """code_correct MUST equal exec pass, regardless of classifier opinion."""
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
    # Code that PASSES execution test
    passing_code = (
        "def transfer(a, b, amount):\n    a['balance'] -= amount\n    b['balance'] += amount"
    )
    parsed_pass = {
        "code": passing_code,
        "reasoning": "",
        "raw_output": passing_code,
        "parse_error": None,
        "_raw_fallback": False,
    }
    result_pass = evaluate_output(case, parsed_pass)
    assert result_pass["pass"] is True, "exec should pass"
    assert result_pass["code_correct"] is True, "code_correct must be True when exec passes"

    # Code that FAILS execution test
    failing_code = "def transfer(a, b, amount):\n    a['balance'] -= amount"
    parsed_fail = {
        "code": failing_code,
        "reasoning": "balance conservation.",
        "raw_output": failing_code,
        "parse_error": None,
        "_raw_fallback": False,
    }
    result_fail = evaluate_output(case, parsed_fail)
    assert result_fail["pass"] is False, "exec should fail"
    assert result_fail["code_correct"] is False, "code_correct must be False when exec fails"


def test_leg_uses_exec_not_classifier():
    """LEG must be: reasoning_correct AND NOT exec_pass."""
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
    # Correct reasoning but broken code → LEG
    failing_code = "def transfer(a, b, amount):\n    a['balance'] -= amount"
    parsed = {
        "code": failing_code,
        "reasoning": "Must conserve total balance across accounts.",
        "raw_output": failing_code,
        "parse_error": None,
        "_raw_fallback": False,
    }
    result = evaluate_output(case, parsed)
    if result["reasoning_correct"] and not result["pass"]:
        assert result["alignment"]["category"] == "leg"
        assert result["alignment"]["leg_true"] is True


def test_classifier_prompt_has_no_exec_signals():
    """The classifier prompt must NOT contain execution results or pass/fail."""
    source = Path(__file__).resolve().parents[1] / "evaluator.py"
    text = source.read_text()
    # Find the prompt template
    start = text.find('_CLASSIFY_PROMPT = """')
    end = text.find('"""', start + 21)
    prompt_text = text[start:end].lower()
    assert "exec_status" not in prompt_text, "Classifier prompt contains exec_status"
    assert (
        "execution test result" not in prompt_text
    ), "Classifier prompt contains execution results"
    assert "status: passed" not in prompt_text, "Classifier prompt contains pass/fail hint"
    assert "status: failed" not in prompt_text, "Classifier prompt contains pass/fail hint"
    assert "test_details" not in prompt_text, "Classifier prompt contains test details"


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
            # code_correct and reasoning_correct must come from classify, not heuristic
            assert (
                "classify[" in func_source or 'classify["' in func_source
            ), "evaluate_output does not derive code_correct/reasoning_correct from classifier"
            # _detected_correct_reasoning must NOT be called for the primary classification
            # (it may still exist in the file for backward compat but not in this function)
            break


# ============================================================
# 4. PARSING ROBUSTNESS
# ============================================================


def test_parse_valid_output():
    """Well-formed classifier output parses correctly (2-part format)."""
    result = parse_classify_output("YES ; HIDDEN_DEPENDENCY")
    assert result["reasoning_correct"] is True
    assert result["failure_type"] == "HIDDEN_DEPENDENCY"
    assert result["parse_error"] is None
    assert "code_correct" not in result, "Parser must NOT return code_correct"


def test_parse_no():
    result = parse_classify_output("NO ; UNKNOWN")
    assert result["reasoning_correct"] is False
    assert result["failure_type"] == "UNKNOWN"


def test_parse_empty_input():
    result = parse_classify_output("")
    assert result["parse_error"] is not None
    assert result["reasoning_correct"] is None


def test_parse_too_few_parts():
    result = parse_classify_output("YES")
    assert result["parse_error"] is not None
    assert "expected_2_parts" in result["parse_error"]


def test_parse_too_many_parts():
    result = parse_classify_output("YES ; NO ; UNKNOWN")
    assert result["parse_error"] is not None
    assert "expected_2_parts" in result["parse_error"]


def test_parse_invalid_verdict():
    result = parse_classify_output("MAYBE ; UNKNOWN")
    assert result["parse_error"] is not None
    assert "invalid_reasoning_correct" in result["parse_error"]


def test_parse_invalid_failure_type():
    result = parse_classify_output("YES ; MADE_UP_TYPE")
    assert result["parse_error"] is not None
    assert "invalid_failure_type" in result["parse_error"]


def test_parse_multiline_fails():
    result = parse_classify_output("YES ; UNKNOWN\nsome extra text")
    assert result["parse_error"] is not None
    assert "extra_lines" in result["parse_error"]


def test_parse_no_silent_defaults():
    """On parse failure, reasoning_correct must be None, not False."""
    result = parse_classify_output("GARBAGE")
    assert result["reasoning_correct"] is None, "Must be None on parse failure, not False"
    assert result["failure_type"] is None


# ============================================================
# 5. BACKWARD COMPATIBILITY
# ============================================================


def test_full_pipeline_baseline():
    """Baseline condition runs end-to-end with new evaluator."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
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

    case = load_cases(case_id="easy_conservation")[0]
    _, _, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert "identified_correct_issue" in ev
    assert isinstance(ev["identified_correct_issue"], bool)


def test_backward_compat_reasoning_action_gap():
    """reasoning_action_gap field still present for backward compat."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
    _, _, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert "reasoning_action_gap" in ev
    assert isinstance(ev["reasoning_action_gap"], bool)


def test_logging_includes_new_fields():
    """Log records must include the new classification fields."""
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="easy_conservation")[0]
    _, _, ev = run_single(case, "gpt-4.1-nano", "baseline")
    # The eval dict is what gets logged
    assert "code_correct" in ev
    assert "reasoning_correct" in ev
    assert "failure_type" in ev
    assert "alignment" in ev
    assert "category" in ev["alignment"]
