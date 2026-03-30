"""Tests for the extended invariant type system.

Validates:
1. All 28 families map to an invariant type
2. New invariant types (field_sync, state_conservation, atomicity) work
3. No regression on existing types
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import Artifact, ExecutionState
from graph_runner.executors.exec_eval import (
    exec_eval_executor,
    infer_invariant_type,
    INVARIANT_TYPE_REGISTRY,
)

BASE = Path(__file__).resolve().parents[1]


def _make_state(code: str, contract: dict, case_meta: dict | None = None) -> ExecutionState:
    state = ExecutionState()
    case = case_meta or {"id": "test", "family": "test"}
    case["test_contract"] = contract
    state.add_artifact("case", Artifact.create(type="case", value=case))
    state.add_artifact("parsed_response", Artifact.create(
        type="parsed_response", value={"reasoning": "test", "code": code}
    ))
    return state


def _run(code: str, contract: dict, case_meta: dict | None = None) -> dict:
    state = _make_state(code, contract, case_meta)
    result = exec_eval_executor(state)
    return result.state.get("exec_result").value


# ============================================================
# META-TEST: All cases have invariant types
# ============================================================

def test_all_cases_have_invariant_type() -> None:
    print("[TEST: ALL CASES HAVE INVARIANT TYPE]")
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    unmapped = []
    for case in cases:
        try:
            inv_type = infer_invariant_type(case)
            assert inv_type in INVARIANT_TYPE_REGISTRY, f"{inv_type} not in registry"
        except ValueError as e:
            unmapped.append(str(e))

    if unmapped:
        for u in unmapped:
            print(f"  UNMAPPED: {u}")
        assert False, f"{len(unmapped)} cases unmapped"

    print(f"  All {len(cases)} cases mapped to invariant types")
    print("  PASS\n")


# ============================================================
# field_sync
# ============================================================

def test_field_sync_pass() -> None:
    code = (
        "def update_profile():\n"
        "    return {'name': 'Alice', 'display_name': 'Alice'}\n"
    )
    contract = {
        "function": "update_profile",
        "tests": [{"type": "field_sync", "primary_field": "name", "dependent_field": "display_name"}],
    }
    val = _run(code, contract)
    print(f"[TEST: FIELD_SYNC PASS]")
    print(f"  success={val['success']}, error={val['error']}")
    assert val["success"] is True
    print("  PASS\n")


def test_field_sync_fail() -> None:
    code = (
        "def update_profile():\n"
        "    return {'name': 'Alice', 'display_name': 'OLD_NAME'}\n"
    )
    contract = {
        "function": "update_profile",
        "tests": [{"type": "field_sync", "primary_field": "name", "dependent_field": "display_name"}],
    }
    val = _run(code, contract)
    print(f"[TEST: FIELD_SYNC FAIL]")
    print(f"  success={val['success']}, error={val['error']}")
    assert val["success"] is False
    assert "field_sync violated" in val["error"]
    print("  PASS\n")


# ============================================================
# state_conservation
# ============================================================

def test_state_conservation_pass() -> None:
    code = "def f(): return 42\n"
    contract = {
        "function": "f",
        "tests": [{"type": "state_conservation"}],
    }
    val = _run(code, contract)
    print(f"[TEST: STATE_CONSERVATION PASS]")
    print(f"  success={val['success']}, error={val['error']}")
    assert val["success"] is True
    print("  PASS\n")


def test_state_conservation_fail() -> None:
    code = (
        "counter = {'n': 0}\n"
        "def f():\n"
        "    counter['n'] += 1\n"
        "    return counter['n']\n"
    )
    contract = {
        "function": "f",
        "tests": [{"type": "state_conservation"}],
    }
    val = _run(code, contract)
    print(f"[TEST: STATE_CONSERVATION FAIL]")
    print(f"  success={val['success']}, error={val['error']}")
    assert val["success"] is False
    assert "state_conservation violated" in val["error"]
    print("  PASS\n")


# ============================================================
# atomicity
# ============================================================

def test_atomicity_pass() -> None:
    code = "def f(): return 1\n"
    contract = {
        "function": "f",
        "tests": [{"type": "atomicity"}],
    }
    val = _run(code, contract)
    print(f"[TEST: ATOMICITY PASS]")
    print(f"  success={val['success']}, error={val['error']}")
    assert val["success"] is True
    print("  PASS\n")


def test_atomicity_fail_with_check() -> None:
    code = (
        "state = {'balance': 100}\n"
        "def transfer():\n"
        "    state['balance'] -= 50\n"
        "    raise ValueError('payment failed')\n"
    )
    contract = {
        "function": "transfer",
        "tests": [{
            "type": "atomicity",
            "check": "lambda g: g.get('state', {}).get('balance') == 100",
        }],
    }
    val = _run(code, contract)
    print(f"[TEST: ATOMICITY FAIL]")
    print(f"  success={val['success']}, error={val['error']}")
    assert val["success"] is False
    assert "atomicity violated" in val["error"]
    print("  PASS\n")


# ============================================================
# REGRESSION: existing types still work
# ============================================================

def test_independence_regression() -> None:
    val = _run(
        "DEFAULTS = {'timeout': 30}\ndef f(): return DEFAULTS.copy()",
        {"function": "f", "tests": [{"type": "independence", "mutation": {"timeout": 999}}]},
    )
    print(f"[TEST: INDEPENDENCE REGRESSION]")
    assert val["success"] is True
    print("  PASS\n")


def test_idempotence_regression() -> None:
    val = _run(
        "def f(): return 1",
        {"function": "f", "tests": [{"type": "idempotence"}]},
    )
    print(f"[TEST: IDEMPOTENCE REGRESSION]")
    assert val["success"] is True
    print("  PASS\n")


def test_consistency_regression() -> None:
    val = _run(
        "def f(): return {'a': 1, 'b': 2}",
        {"function": "f", "tests": [{"type": "consistency", "check": "lambda r: r['a'] <= r['b']"}]},
    )
    print(f"[TEST: CONSISTENCY REGRESSION]")
    assert val["success"] is True
    print("  PASS\n")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_all_cases_have_invariant_type()
    passed += 1

    test_field_sync_pass()
    passed += 1
    test_field_sync_fail()
    passed += 1

    test_state_conservation_pass()
    passed += 1
    test_state_conservation_fail()
    passed += 1

    test_atomicity_pass()
    passed += 1
    test_atomicity_fail_with_check()
    passed += 1

    test_independence_regression()
    passed += 1
    test_idempotence_regression()
    passed += 1
    test_consistency_regression()
    passed += 1

    print(f"{'=' * 50}")
    print(f"RESULTS: {passed}/10 passed")
    print("ALL TESTS PASSED")
    print()
    print("Invariant type system covers all 28 families. New types work. No regression.")


if __name__ == "__main__":
    main()
