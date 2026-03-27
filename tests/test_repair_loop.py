"""Test repair loop behavior: max 2 attempts, second uses error feedback."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import json

# Force mock mode
os.environ["OPENAI_API_KEY"] = "sk-dummy"

from execution import run_repair_loop as _run_repair_loop
from runner import load_cases


def test_repair_loop_runs():
    """Repair loop should run without crashing on a real case."""
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    cid, cond, ev = _run_repair_loop(case, "gpt-4.1-nano")

    assert cid == "l3_state_pipeline"
    assert cond == "repair_loop"
    assert "attempts" in ev
    assert "num_attempts" in ev
    assert "final_pass" in ev


def test_repair_loop_max_two_attempts():
    """If first attempt fails, second attempt runs. Never more than 2."""
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")

    assert ev["num_attempts"] <= 2
    assert len(ev["attempts"]) <= 2


def test_repair_loop_attempts_structure():
    """Each attempt has the right fields."""
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")

    for attempt in ev["attempts"]:
        assert "attempt" in attempt
        assert "pass" in attempt
        assert "score" in attempt


def test_repair_loop_second_attempt_triggered_on_failure():
    """If first attempt fails, there must be a second attempt."""
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")

    first = ev["attempts"][0]
    if not first["pass"]:
        assert ev["num_attempts"] == 2
        assert len(ev["attempts"]) == 2


def test_repair_loop_final_pass_matches_last_attempt():
    """final_pass should reflect the last attempt's result."""
    cases = load_cases(case_id="l3_state_pipeline")
    case = cases[0]
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")

    last = ev["attempts"][-1]
    assert ev["final_pass"] == last["pass"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
