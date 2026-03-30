"""Tests for guarded GraphRunner execution.

3 cases:
1. Full success path: prompt → generate → parse → exec_eval
2. Parse failure blocks exec_eval via guard
3. Missing raw_response skips parse and exec_eval via guards
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.state import Artifact, ExecutionState
from graph_runner.graph_runner import GraphRunner
from graph_runner.graph_factory import build_minimal_graph


def print_state(name: str, state: ExecutionState) -> None:
    print(f"[TEST: {name}]")
    for key in ["prompt", "raw_response", "parsed_response", "parse_error",
                 "exec_result", "exec_contract_error"]:
        present = state.has(key)
        print(f"  {key}: {present}")
        if present and key in ("exec_result", "parse_error"):
            print(f"    value: {state.get(key).value}")


# ============================================================
# CASE 1 — FULL SUCCESS PATH
# ============================================================

def test_full_success() -> None:
    state = ExecutionState()
    state.add_artifact(
        "prompt",
        Artifact.create(type="prompt", value="Fix the aliasing bug."),
    )

    graph = build_minimal_graph()
    runner = GraphRunner(graph)
    state = runner.run(state)

    print_state("FULL SUCCESS PATH", state)

    # All stages ran
    assert state.has("prompt"), "prompt must exist"
    assert state.has("raw_response"), "raw_response must exist (generate ran)"
    assert state.has("parsed_response"), "parsed_response must exist (parse ran)"
    assert state.has("exec_result"), "exec_result must exist (exec_eval ran)"
    assert not state.has("parse_error"), "parse_error must not exist"
    assert not state.has("exec_contract_error"), "exec_contract_error must not exist"

    # exec_result is success
    assert state.get("exec_result").value["success"] is True
    assert state.get("exec_result").value["error"] is None

    print("  PASS\n")


# ============================================================
# CASE 2 — PARSE FAILURE BLOCKS EXEC
# ============================================================

def test_parse_failure_blocks_exec() -> None:
    state = ExecutionState()

    # Inject a raw_response that will fail parsing (missing "code" key)
    state.add_artifact(
        "raw_response",
        Artifact.create(
            type="raw_response",
            value={"reasoning": "only reasoning, no code"},
        ),
    )

    graph = build_minimal_graph()
    runner = GraphRunner(graph)
    state = runner.run(state)

    print_state("PARSE FAILURE BLOCKS EXEC", state)

    # generate skipped (no prompt)
    assert not state.has("prompt"), "prompt was not injected"

    # parse ran and failed
    assert state.has("raw_response"), "raw_response was injected"
    assert state.has("parse_error"), "parse_error must exist (parse failed)"
    assert not state.has("parsed_response"), "parsed_response must not exist"

    # exec_eval must NOT have run — guard (can_execute) blocks it
    assert not state.has("exec_result"), "exec_result must NOT exist (guard blocked exec_eval)"
    assert not state.has("exec_contract_error"), "exec_contract_error must not exist"

    print("  PASS\n")


# ============================================================
# CASE 3 — MISSING RAW_RESPONSE SKIPS EVERYTHING DOWNSTREAM
# ============================================================

def test_missing_raw_response() -> None:
    state = ExecutionState()

    # Inject nothing — no prompt, no raw_response

    graph = build_minimal_graph()
    runner = GraphRunner(graph)
    state = runner.run(state)

    print_state("MISSING RAW_RESPONSE", state)

    # All stages skipped by guards
    assert not state.has("prompt"), "no prompt injected"
    assert not state.has("raw_response"), "no raw_response (generate skipped)"
    assert not state.has("parsed_response"), "no parsed_response (parse skipped)"
    assert not state.has("parse_error"), "no parse_error (parse skipped)"
    assert not state.has("exec_result"), "no exec_result (exec_eval skipped)"

    print("  PASS\n")


# ============================================================
# MAIN
# ============================================================

def main():
    passed = 0

    test_full_success()
    passed += 1

    test_parse_failure_blocks_exec()
    passed += 1

    test_missing_raw_response()
    passed += 1

    print(f"{'=' * 40}")
    print(f"RESULTS: {passed}/3 passed")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
