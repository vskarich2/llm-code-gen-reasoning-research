"""Tests for idempotence and consistency invariant types.

Validates that new primitives integrate cleanly into the dispatcher
without regression on existing independence tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import Artifact, ExecutionState
from graph_runner.executors.exec_eval import exec_eval_executor


def _make_state(code: str, contract: dict) -> ExecutionState:
    state = ExecutionState()
    state.add_artifact("case", Artifact.create(type="case", value={"id": "test", "test_contract": contract}))
    state.add_artifact("parsed_response", Artifact.create(type="parsed_response", value={"reasoning": "test", "code": code}))
    return state


def _run(code: str, contract: dict) -> dict:
    state = _make_state(code, contract)
    result = exec_eval_executor(state)
    return result.state.get("exec_result").value


def print_result(name: str, val: dict) -> None:
    print(f"[TEST: {name}]")
    print(f"  success:      {val['success']}")
    print(f"  error:        {val['error']}")
    print(f"  tests_run:    {val['tests_run']}")
    print(f"  tests_passed: {val['tests_passed']}")


# ============================================================
# IDEMPOTENCE
# ============================================================

def test_idempotence_pass() -> None:
    val = _run(
        "def f(): return 1",
        {"function": "f", "tests": [{"type": "idempotence"}]},
    )
    print_result("IDEMPOTENCE PASS", val)
    assert val["success"] is True
    assert val["error"] is None
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 1
    print("  PASS\n")


def test_idempotence_fail() -> None:
    code = "counter = {'x': 0}\ndef f():\n    counter['x'] += 1\n    return counter['x']"
    val = _run(
        code,
        {"function": "f", "tests": [{"type": "idempotence"}]},
    )
    print_result("IDEMPOTENCE FAIL", val)
    assert val["success"] is False
    assert "idempotence violated" in val["error"]
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0
    print("  PASS\n")


# ============================================================
# CONSISTENCY
# ============================================================

def test_consistency_pass() -> None:
    val = _run(
        "def f(): return {'a': 1, 'b': 2}",
        {"function": "f", "tests": [{"type": "consistency", "check": "lambda result: result['a'] <= result['b']"}]},
    )
    print_result("CONSISTENCY PASS", val)
    assert val["success"] is True
    assert val["error"] is None
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 1
    print("  PASS\n")


def test_consistency_fail() -> None:
    val = _run(
        "def f(): return {'a': 3, 'b': 2}",
        {"function": "f", "tests": [{"type": "consistency", "check": "lambda result: result['a'] <= result['b']"}]},
    )
    print_result("CONSISTENCY FAIL", val)
    assert val["success"] is False
    assert "consistency violated" in val["error"]
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0
    print("  PASS\n")


def test_consistency_missing_check() -> None:
    val = _run(
        "def f(): return {'a': 1}",
        {"function": "f", "tests": [{"type": "consistency"}]},
    )
    print_result("CONSISTENCY MISSING CHECK", val)
    assert val["success"] is False
    assert "missing 'check'" in val["error"]
    assert val["tests_run"] == 1
    assert val["tests_passed"] == 0
    print("  PASS\n")


# ============================================================
# REGRESSION — INDEPENDENCE STILL WORKS
# ============================================================

def test_independence_regression() -> None:
    # Correct
    val = _run(
        "DEFAULTS = {'timeout': 30}\ndef f(): return DEFAULTS.copy()",
        {"function": "f", "tests": [{"type": "independence", "mutation": {"timeout": 999}}]},
    )
    print_result("INDEPENDENCE REGRESSION (correct)", val)
    assert val["success"] is True
    print("  PASS\n")

    # Buggy
    val = _run(
        "DEFAULTS = {'timeout': 30}\ndef f(): return DEFAULTS",
        {"function": "f", "tests": [{"type": "independence", "mutation": {"timeout": 999}}]},
    )
    print_result("INDEPENDENCE REGRESSION (buggy)", val)
    assert val["success"] is False
    assert "independence violated" in val["error"]
    print("  PASS\n")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_idempotence_pass()
    passed += 1

    test_idempotence_fail()
    passed += 1

    test_consistency_pass()
    passed += 1

    test_consistency_fail()
    passed += 1

    test_consistency_missing_check()
    passed += 1

    test_independence_regression()
    passed += 2  # two sub-tests

    print(f"{'=' * 50}")
    print(f"RESULTS: {passed}/7 passed")
    print("ALL TESTS PASSED")
    print()
    print("Invariant system extended: idempotence and consistency added without regression or system bloat.")


if __name__ == "__main__":
    main()
