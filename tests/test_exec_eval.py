"""Tests for exec_eval_executor — behavioral ground truth layer.

4 cases: valid code, syntax error, runtime error, upstream parse failure (guard-level skip).
Each case uses fresh ExecutionState. Hard assertions — script crashes on failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import Artifact, ExecutionState
from graph_runner.executors.exec_eval import exec_eval_executor
from graph_runner.transitions import can_execute


def print_result(name: str, state: ExecutionState) -> None:
    print(f"[TEST: {name}]")
    print(f"  exec_result: {state.has('exec_result')}")
    print(f"  exec_contract_error: {state.has('exec_contract_error')}")
    if state.has("exec_result"):
        print(f"  value: {state.get('exec_result').value}")
    if state.has("exec_contract_error"):
        print(f"  contract_error: {state.get('exec_contract_error').value}")


# ============================================================
# CASE 1 — VALID CODE
# ============================================================

def run_valid_case() -> ExecutionState:
    state = ExecutionState()
    state.add_artifact(
        "parsed_response",
        Artifact.create(
            type="parsed_response",
            value={
                "reasoning": "simple valid code with callable",
                "code": "def f(): return 42",
            },
        ),
    )
    result = exec_eval_executor(state)
    return result.state


# ============================================================
# CASE 2 — SYNTAX ERROR
# ============================================================

def run_syntax_error_case() -> ExecutionState:
    state = ExecutionState()
    state.add_artifact(
        "parsed_response",
        Artifact.create(
            type="parsed_response",
            value={
                "reasoning": "bad syntax",
                "code": "def broken(:\n    pass",
            },
        ),
    )
    result = exec_eval_executor(state)
    return result.state


# ============================================================
# CASE 3 — RUNTIME ERROR
# ============================================================

def run_runtime_error_case() -> ExecutionState:
    state = ExecutionState()
    state.add_artifact(
        "parsed_response",
        Artifact.create(
            type="parsed_response",
            value={
                "reasoning": "division by zero",
                "code": "x = 1 / 0",
            },
        ),
    )
    result = exec_eval_executor(state)
    return result.state


# ============================================================
# CASE 4 — UPSTREAM PARSE FAILURE (guard blocks execution)
# ============================================================

def run_parse_failure_case() -> ExecutionState:
    """Simulate upstream parse failure. The guard (can_execute) should
    prevent exec_eval_executor from running. We test the guard directly."""
    state = ExecutionState()
    state.add_artifact(
        "parse_error",
        Artifact.create(
            type="parse_error",
            value="Missing keys: ['code']",
        ),
    )
    return state


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    # Case 1 — VALID CODE
    state = run_valid_case()
    print_result("VALID CODE", state)
    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "exec_contract_error must not exist"
    assert state.get("exec_result").value["success"] is True
    assert state.get("exec_result").value["error"] is None
    print("  PASS\n")
    passed += 1

    # Case 2 — SYNTAX ERROR
    state = run_syntax_error_case()
    print_result("SYNTAX ERROR", state)
    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "exec_contract_error must not exist"
    assert state.get("exec_result").value["success"] is False
    assert "SyntaxError" in state.get("exec_result").value["error"]
    print("  PASS\n")
    passed += 1

    # Case 3 — RUNTIME ERROR
    state = run_runtime_error_case()
    print_result("RUNTIME ERROR", state)
    assert state.has("exec_result"), "exec_result must exist"
    assert not state.has("exec_contract_error"), "exec_contract_error must not exist"
    assert state.get("exec_result").value["success"] is False
    assert "ZeroDivisionError" in state.get("exec_result").value["error"]
    print("  PASS\n")
    passed += 1

    # Case 4 — UPSTREAM PARSE FAILURE (guard check)
    state = run_parse_failure_case()
    print(f"[TEST: UPSTREAM PARSE FAILURE]")
    guard_result = can_execute(state)
    print(f"  can_execute guard: {guard_result}")
    assert guard_result is False, "Guard must block execution when parse_error exists"
    assert not state.has("exec_result"), "exec_result must NOT exist (guard blocks)"
    print("  PASS\n")
    passed += 1

    print(f"{'=' * 40}")
    print(f"RESULTS: {passed}/4 passed")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
