"""Tests for ResponseContract + parse_executor integration.

Validates that:
- Invalid inputs NEVER produce parsed_response
- Valid inputs NEVER produce parse_error
- System never crashes under invalid input
- Error messages are specific and correct
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import ExecutionState, Artifact
from graph_runner.executors.reconstruct import parse_executor


def _make_state(raw_value: object) -> ExecutionState:
    """Create fresh ExecutionState with a raw_response artifact."""
    state = ExecutionState()
    artifact = Artifact.create(type="raw_response", value=raw_value)
    state.add_artifact("raw_response", artifact)
    return state


def _run_test(name: str, raw_value: object,
              expect_parsed: bool, expect_error: bool,
              expected_error_substring: str | None = None) -> bool:
    state = _make_state(raw_value)
    result = parse_executor(state)
    state = result.state

    has_parsed = state.has("parsed_response")
    has_error = state.has("parse_error")

    ok = True

    if has_parsed != expect_parsed:
        print(f"  FAIL: parsed_response expected={expect_parsed}, got={has_parsed}")
        ok = False

    if has_error != expect_error:
        print(f"  FAIL: parse_error expected={expect_error}, got={has_error}")
        ok = False

    if has_error and expected_error_substring:
        error_msg = state.get("parse_error").value
        if expected_error_substring not in error_msg:
            print(f"  FAIL: expected '{expected_error_substring}' in error, got: '{error_msg}'")
            ok = False

    # HARD INVARIANT: parsed_response and parse_error must be mutually exclusive
    if has_parsed and has_error:
        print(f"  FAIL: BOTH parsed_response AND parse_error exist — mutual exclusion violated")
        ok = False

    if not has_parsed and not has_error:
        print(f"  FAIL: NEITHER parsed_response NOR parse_error exist — silent failure")
        ok = False

    error_msg = state.get("parse_error").value if has_error else None

    print(f"[TEST: {name}]")
    print(f"  parsed_response: {has_parsed}")
    print(f"  parse_error: {has_error}")
    if error_msg:
        print(f"  error: {error_msg}")
    print(f"  result: {'PASS' if ok else 'FAIL'}")
    print()

    return ok


def main():
    results = []

    # Case 1 — VALID
    results.append(_run_test(
        name="VALID",
        raw_value={"reasoning": "correct reasoning", "code": "print('hello')"},
        expect_parsed=True,
        expect_error=False,
    ))

    # Case 2 — MISSING KEY
    results.append(_run_test(
        name="MISSING KEY",
        raw_value={"reasoning": "missing code"},
        expect_parsed=False,
        expect_error=True,
        expected_error_substring="Missing keys",
    ))

    # Case 3 — WRONG TYPE
    results.append(_run_test(
        name="WRONG TYPE",
        raw_value={"reasoning": 123, "code": "print('hello')"},
        expect_parsed=False,
        expect_error=True,
        expected_error_substring="reasoning must be a string",
    ))

    # Case 4 — NOT A DICT
    results.append(_run_test(
        name="NOT A DICT",
        raw_value="this is a string",
        expect_parsed=False,
        expect_error=True,
        expected_error_substring="Response must be a dict",
    ))

    passed = sum(results)
    total = len(results)
    print(f"{'=' * 40}")
    print(f"RESULTS: {passed}/{total} passed")
    if passed == total:
        print("ALL TESTS PASSED")
    else:
        print("FAILURES DETECTED")
        sys.exit(1)


if __name__ == "__main__":
    main()
