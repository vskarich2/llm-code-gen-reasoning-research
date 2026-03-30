"""Tests for exec_eval_executor with behavioral ground truth.

4 cases: correct function, runtime error, syntax error, no function.
Hard assertions — script crashes on failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import Artifact, ExecutionState
from graph_runner.executors.exec_eval import exec_eval_executor


def _make_state_with_code(code: str) -> ExecutionState:
    """Create ExecutionState with a parsed_response containing the given code."""
    state = ExecutionState()
    state.add_artifact(
        "parsed_response",
        Artifact.create(
            type="parsed_response",
            value={
                "reasoning": "test",
                "code": code,
            },
        ),
    )
    return state


def print_result(name: str, state: ExecutionState) -> None:
    print(f"[TEST: {name}]")
    print(f"  exec_result: {state.has('exec_result')}")
    print(f"  exec_contract_error: {state.has('exec_contract_error')}")
    if state.has("exec_result"):
        val = state.get("exec_result").value
        print(f"  success: {val['success']}")
        print(f"  error: {val['error']}")
        print(f"  tests_run: {val['tests_run']}")
        print(f"  tests_passed: {val['tests_passed']}")


# ============================================================
# CASE 1 — CORRECT FUNCTION
# ============================================================

def test_correct_function() -> None:
    state = _make_state_with_code("def f(): return 1")
    result = exec_eval_executor(state)
    state = result.state

    print_result("CORRECT FUNCTION", state)

    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "no contract error"
    val = state.get("exec_result").value
    assert val["success"] is True, f"Expected success=True, got {val['success']}"
    assert val["error"] is None, f"Expected error=None, got {val['error']}"
    assert val["tests_run"] == 1, f"Expected tests_run=1, got {val['tests_run']}"
    assert val["tests_passed"] == 1, f"Expected tests_passed=1, got {val['tests_passed']}"

    print("  PASS\n")


# ============================================================
# CASE 2 — RUNTIME ERROR
# ============================================================

def test_runtime_error() -> None:
    state = _make_state_with_code("def f(): return 1/0")
    result = exec_eval_executor(state)
    state = result.state

    print_result("RUNTIME ERROR", state)

    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "no contract error"
    val = state.get("exec_result").value
    assert val["success"] is False, f"Expected success=False, got {val['success']}"
    assert "ZeroDivisionError" in val["error"], f"Expected ZeroDivisionError in error, got: {val['error']}"
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0

    print("  PASS\n")


# ============================================================
# CASE 3 — SYNTAX ERROR
# ============================================================

def test_syntax_error() -> None:
    state = _make_state_with_code("def f(: pass")
    result = exec_eval_executor(state)
    state = result.state

    print_result("SYNTAX ERROR", state)

    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "no contract error"
    val = state.get("exec_result").value
    assert val["success"] is False
    assert "SyntaxError" in val["error"], f"Expected SyntaxError in error, got: {val['error']}"
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0

    print("  PASS\n")


# ============================================================
# CASE 4 — NO FUNCTION
# ============================================================

def test_no_function() -> None:
    state = _make_state_with_code("x = 1")
    result = exec_eval_executor(state)
    state = result.state

    print_result("NO FUNCTION", state)

    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "no contract error"
    val = state.get("exec_result").value
    assert val["success"] is False, f"Expected success=False, got {val['success']}"
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0
    assert "No callable" in val["error"], f"Expected 'No callable' in error, got: {val['error']}"

    print("  PASS\n")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_correct_function()
    passed += 1

    test_runtime_error()
    passed += 1

    test_syntax_error()
    passed += 1

    test_no_function()
    passed += 1

    print(f"{'=' * 40}")
    print(f"RESULTS: {passed}/4 passed")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
