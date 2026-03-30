"""Single-case real LLM integration test.

Runs ONE case (alias_config_a) through the full graph_runner pipeline
with a REAL LLM call. Temperature=0. No retries. No fallbacks.

Valid outcomes:
  A) Perfect output → parsed_response + exec_result
  B) JSON failure → parse_error, no exec_result
  C) Bad code → parsed_response + exec_result.success=False
All are correct behavior. System must NOT crash.
"""

import json
import os
import sys
from pathlib import Path

# Enable real LLM for this test
os.environ["GRAPH_RUNNER_REAL_LLM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph_runner.adapters.legacy_adapter import load_case_into_state
from graph_runner.graph_runner import GraphRunner
from graph_runner.graph_factory import build_minimal_graph

BASE = Path(__file__).resolve().parents[1]


def load_case() -> dict:
    cases = json.loads((BASE / "cases_v2.json").read_text(encoding="utf-8"))
    case = next(c for c in cases if c["id"] == "alias_config_a")
    case["code_files_contents"] = {}
    for rel in case.get("code_files", []):
        full_path = BASE / rel
        if full_path.exists():
            case["code_files_contents"][rel] = full_path.read_text(encoding="utf-8")
    return case


def main():
    case = load_case()
    print(f"Case: {case['id']} (difficulty={case['difficulty']})")
    print()

    state = load_case_into_state(case)
    graph = build_minimal_graph()
    runner = GraphRunner(graph)
    final_state = runner.run(state)

    # Print results
    print("[REAL LLM TEST]")
    print(f"  prompt exists:          {final_state.has('prompt')}")
    print(f"  raw_llm_text exists:    {final_state.has('raw_llm_text')}")
    print(f"  raw_response exists:    {final_state.has('raw_response')}")
    print(f"  parsed_response exists: {final_state.has('parsed_response')}")
    print(f"  parse_error exists:     {final_state.has('parse_error')}")
    print(f"  exec_result exists:     {final_state.has('exec_result')}")
    print()

    # Print raw LLM output (shortened)
    if final_state.has("raw_llm_text"):
        raw = final_state.get("raw_llm_text").value
        print(f"  raw LLM output ({len(raw)} chars):")
        print(f"    {raw[:300]}")
        print()

    if final_state.has("exec_result"):
        print(f"  exec_result: {final_state.get('exec_result').value}")
        print()

    if final_state.has("parse_error"):
        print(f"  parse_error: {final_state.get('parse_error').value}")
        print()

    # Hard assertions — must not crash
    assert final_state.has("prompt"), "prompt must exist"
    assert final_state.has("raw_llm_text"), "raw_llm_text must exist (LLM was called)"

    # Either parsing succeeded or failed — both are valid
    has_parsed = final_state.has("parsed_response")
    has_error = final_state.has("parse_error")
    assert has_parsed or has_error, (
        "System must produce either parsed_response or parse_error — got neither"
    )

    # If parsed, exec must have run (guard allows it)
    if has_parsed:
        assert final_state.has("exec_result"), (
            "parsed_response exists but exec_result is missing — exec_eval did not run"
        )

    # Determine outcome
    if has_parsed and final_state.has("exec_result"):
        exec_val = final_state.get("exec_result").value
        if exec_val["success"]:
            outcome = "A (perfect output — code executes successfully)"
        else:
            outcome = f"C (bad code — {exec_val['error']})"
    elif has_error:
        outcome = f"B (JSON failure — {final_state.get('parse_error').value})"
    else:
        outcome = "UNKNOWN"

    print(f"  OUTCOME: {outcome}")
    print()
    print("SYSTEM DID NOT CRASH")


if __name__ == "__main__":
    main()
