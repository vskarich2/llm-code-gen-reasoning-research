"""Test that existing conditions still work without crashes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

os.environ["OPENAI_API_KEY"] = "sk-dummy"

from execution import run_single as _run_single, build_prompt as _build_prompt
from runner import load_cases


def test_baseline_runs():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    cid, cond, ev = _run_single(case, "gpt-4.1-nano", "baseline")
    assert cid == "l3_state_pipeline"
    assert cond == "baseline"
    assert "pass" in ev
    assert "score" in ev


def test_diagnostic_runs():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    cid, cond, ev = _run_single(case, "gpt-4.1-nano", "diagnostic")
    assert cond == "diagnostic"
    assert "pass" in ev


def test_guardrail_runs():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    cid, cond, ev = _run_single(case, "gpt-4.1-nano", "guardrail")
    assert cond == "guardrail"


def test_all_original_conditions_build_prompt():
    """Every original condition produces a non-empty prompt."""
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    for cond in [
        "baseline",
        "diagnostic",
        "guardrail",
        "guardrail_strict",
        "counterfactual",
        "reason_then_act",
        "self_check",
    ]:
        prompt, op = _build_prompt(case, cond)
        assert len(prompt) > 100, f"{cond} prompt too short"


def test_new_conditions_build_prompt():
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    for cond in ["counterfactual_check", "test_driven", "repair_loop"]:
        prompt, op = _build_prompt(case, cond)
        assert len(prompt) > 100, f"{cond} prompt too short"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
