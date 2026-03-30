"""Semantic invariant tests for alias_config_a.

Proves that the system detects aliasing bugs — code that runs
but violates the invariant "mutation must not leak across instances".

4 cases: correct fix, aliasing bug, missing function, wrong return type.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import Artifact, ExecutionState
from graph_runner.executors.exec_eval import exec_eval_executor

BASE = Path(__file__).resolve().parents[1]


CONTRACT = {
    "function": "create_config",
    "tests": [
        {"type": "independence", "mutation": {"timeout": 999}},
    ],
}


def _make_state(code: str) -> ExecutionState:
    """Create state with parsed_response and case with machine-executable contract."""
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == "alias_config_a")
    case["test_contract"] = CONTRACT

    state = ExecutionState()
    state.add_artifact(
        "case",
        Artifact.create(type="case", value=case),
    )
    state.add_artifact(
        "parsed_response",
        Artifact.create(
            type="parsed_response",
            value={"reasoning": "test", "code": code},
        ),
    )
    return state


def print_result(name: str, state: ExecutionState) -> None:
    print(f"[TEST: {name}]")
    if state.has("exec_result"):
        val = state.get("exec_result").value
        print(f"  success:      {val['success']}")
        print(f"  error:        {val['error']}")
        print(f"  tests_run:    {val['tests_run']}")
        print(f"  tests_passed: {val['tests_passed']}")
    elif state.has("exec_contract_error"):
        print(f"  contract_error: {state.get('exec_contract_error').value}")


# ============================================================
# TEST 1 — CORRECT IMPLEMENTATION (.copy())
# ============================================================

def test_correct_implementation() -> None:
    code = "DEFAULTS = {'timeout': 30}\ndef create_config(): return DEFAULTS.copy()"
    state = _make_state(code)
    result = exec_eval_executor(state)
    state = result.state

    print_result("CORRECT IMPLEMENTATION", state)

    assert state.has("exec_result"), "exec_result must exist"
    val = state.get("exec_result").value
    assert val["success"] is True, f"Expected success=True, got: {val}"
    assert val["error"] is None
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 1

    print("  PASS\n")


# ============================================================
# TEST 2 — ALIASING BUG (returns DEFAULTS directly)
# ============================================================

def test_aliasing_bug() -> None:
    code = "DEFAULTS = {'timeout': 30}\ndef create_config(): return DEFAULTS"
    state = _make_state(code)
    result = exec_eval_executor(state)
    state = result.state

    print_result("ALIASING BUG", state)

    assert state.has("exec_result"), "exec_result must exist"
    val = state.get("exec_result").value
    assert val["success"] is False, f"CRITICAL: aliasing bug MUST fail, got success=True"
    assert "independence violated" in val["error"], f"Error must mention independence, got: {val['error']}"
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0

    print("  PASS\n")


# ============================================================
# TEST 3 — MISSING FUNCTION
# ============================================================

def test_missing_function() -> None:
    code = "x = 1"
    state = _make_state(code)
    result = exec_eval_executor(state)
    state = result.state

    print_result("MISSING FUNCTION", state)

    assert state.has("exec_result"), "exec_result must exist"
    val = state.get("exec_result").value
    assert val["success"] is False
    assert "not found" in val["error"], f"Error must mention missing fn, got: {val['error']}"
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0

    print("  PASS\n")


# ============================================================
# TEST 4 — WRONG RETURN TYPE
# ============================================================

def test_wrong_return_type() -> None:
    code = "def create_config(): return 42"
    state = _make_state(code)
    result = exec_eval_executor(state)
    state = result.state

    print_result("WRONG RETURN TYPE", state)

    assert state.has("exec_result"), "exec_result must exist"
    val = state.get("exec_result").value
    assert val["success"] is False
    assert "not dict" in val["error"], f"Error must mention type, got: {val['error']}"
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0

    print("  PASS\n")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_correct_implementation()
    passed += 1

    test_aliasing_bug()
    passed += 1

    test_missing_function()
    passed += 1

    test_wrong_return_type()
    passed += 1

    print(f"{'=' * 50}")
    print(f"RESULTS: {passed}/4 passed")
    print("ALL TESTS PASSED")
    print()
    print("Semantic invariant enforcement works: aliasing bug correctly fails.")


if __name__ == "__main__":
    main()
