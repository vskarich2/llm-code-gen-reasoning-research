"""Stress test: 4 forced LLM failure modes through the full pipeline.

Proves system integrity under adversarial outputs:
1. Malformed JSON → parse_error, no exec
2. Missing key → parse_error, no exec
3. Wrong type → parse_error, no exec
4. Semantic failure → passes (exposes evaluation gap)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import graph_runner.executors.generate as gen_module
from graph_runner.adapters.legacy_adapter import load_case_into_state
from graph_runner.graph_runner import GraphRunner
from graph_runner.graph_factory import build_minimal_graph

BASE = Path(__file__).resolve().parents[1]


def _load_case() -> dict:
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == "alias_config_a")
    case["code_files_contents"] = {}
    for rel in case.get("code_files", []):
        p = BASE / rel
        if p.exists():
            case["code_files_contents"][rel] = p.read_text(encoding="utf-8")
    return case


def _run_with_mode(mode: str) -> "ExecutionState":
    """Set forced failure mode, run full pipeline, reset mode."""
    gen_module.FORCE_FAILURE_MODE = mode
    try:
        case = _load_case()
        state = load_case_into_state(case)
        graph = build_minimal_graph()
        runner = GraphRunner(graph)
        return runner.run(state)
    finally:
        gen_module.FORCE_FAILURE_MODE = None


def _print_state(name: str, state) -> None:
    print(f"[FAILURE MODE: {name}]")
    print(f"  raw_llm_text:     {state.has('raw_llm_text')}")
    print(f"  raw_response:     {state.has('raw_response')}")
    print(f"  parsed_response:  {state.has('parsed_response')}")
    print(f"  parse_error:      {state.has('parse_error')}")
    print(f"  exec_result:      {state.has('exec_result')}")
    if state.has("parse_error"):
        print(f"  error: {state.get('parse_error').value}")
    if state.has("exec_result"):
        print(f"  exec_result: {state.get('exec_result').value}")


def main():
    passed = 0

    # ============================================================
    # MODE 1 — MALFORMED JSON
    # ============================================================
    state = _run_with_mode("malformed_json")
    _print_state("MALFORMED JSON", state)

    assert state.has("raw_llm_text"), "raw_llm_text must exist"
    assert state.has("parse_error"), "parse_error must exist"
    assert not state.has("parsed_response"), "parsed_response must NOT exist"
    assert not state.has("exec_result"), "exec_result must NOT exist (guards block)"

    print("  PASS\n")
    passed += 1

    # ============================================================
    # MODE 2 — MISSING KEY
    # ============================================================
    state = _run_with_mode("missing_key")
    _print_state("MISSING KEY", state)

    assert state.has("raw_llm_text"), "raw_llm_text must exist"
    assert state.has("parse_error"), "parse_error must exist"
    assert "Missing keys" in state.get("parse_error").value
    assert not state.has("parsed_response"), "parsed_response must NOT exist"
    assert not state.has("exec_result"), "exec_result must NOT exist"

    print("  PASS\n")
    passed += 1

    # ============================================================
    # MODE 3 — WRONG TYPE
    # ============================================================
    state = _run_with_mode("wrong_type")
    _print_state("WRONG TYPE", state)

    assert state.has("raw_llm_text"), "raw_llm_text must exist"
    assert state.has("parse_error"), "parse_error must exist"
    assert "string" in state.get("parse_error").value
    assert not state.has("parsed_response"), "parsed_response must NOT exist"
    assert not state.has("exec_result"), "exec_result must NOT exist"

    print("  PASS\n")
    passed += 1

    # ============================================================
    # MODE 4 — SEMANTIC FAILURE
    # ============================================================
    state = _run_with_mode("semantic_failure")
    _print_state("SEMANTIC FAILURE", state)

    assert state.has("raw_llm_text"), "raw_llm_text must exist"
    assert state.has("parsed_response"), "parsed_response must exist (valid JSON)"
    assert not state.has("parse_error"), "parse_error must NOT exist"
    assert state.has("exec_result"), "exec_result must exist"

    result = state.get("exec_result").value
    assert result["success"] is True, f"Expected success=True, got: {result}"

    print()
    print("  [SEMANTIC GAP DETECTED]")
    print("  Code executed successfully but may be logically incorrect.")
    print("  Current execution model cannot detect invariant violations.")
    print("  PASS\n")
    passed += 1

    # ============================================================
    # SUMMARY
    # ============================================================
    print(f"{'=' * 50}")
    print(f"RESULTS: {passed}/4 passed")
    print("ALL FAILURE MODES HANDLED CORRECTLY")
    print()
    print("System correctly rejects structural failures and exposes semantic evaluation gap.")


if __name__ == "__main__":
    main()
