"""Test that result dicts have all required fields."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

os.environ["OPENAI_API_KEY"] = "sk-dummy"

from execution import run_single as _run_single, run_repair_loop as _run_repair_loop
from runner import load_cases


def test_standard_result_fields():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_single(case, "gpt-4.1-nano", "baseline")

    assert "pass" in ev
    assert "score" in ev
    assert "reasons" in ev
    assert "failure_modes" in ev
    assert "operator_used" in ev
    assert "condition" in ev
    assert "alignment" in ev
    assert isinstance(ev["pass"], bool)
    assert isinstance(ev["score"], (int, float))


def test_repair_loop_result_fields():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")

    # Repair loop adds these fields
    assert "attempts" in ev
    assert "final_pass" in ev
    assert "num_attempts" in ev
    assert isinstance(ev["attempts"], list)
    assert isinstance(ev["num_attempts"], int)
    assert isinstance(ev["final_pass"], bool)

    # Must also have standard fields
    assert "pass" in ev
    assert "score" in ev
    assert "alignment" in ev


def test_alignment_structure():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_single(case, "gpt-4.1-nano", "baseline")

    alignment = ev["alignment"]
    assert "category" in alignment
    assert alignment["category"] in [
        "true_success",
        "leg",
        "lucky_fix",
        "true_failure",
        "unclassified",
    ]
    assert "code_correct" in alignment
    assert "reasoning_correct" in alignment
    assert "leg_true" in alignment
    assert "lucky_fix" in alignment


def test_execution_structure():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_single(case, "gpt-4.1-nano", "baseline")

    execution = ev.get("execution", {})
    assert "status" in execution
    assert execution["status"] in ["passed", "failed", "error"]
    assert "passed_tests" in execution
    assert "total_tests" in execution


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
