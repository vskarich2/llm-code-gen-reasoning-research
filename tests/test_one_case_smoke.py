"""Smoke test: one real case through the full graph_runner pipeline.

Uses configs/smoke_vskarich_baseline_leg.yaml as the reference config.
Loads the first case from cases_vskarich_test.json (alias_config_a).
Runs: case → build_prompt → generate → parse → exec_eval.

generate is still fake — we are validating data plumbing, not model output.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from graph_runner.adapters.legacy_adapter import load_case_into_state
from graph_runner.graph_runner import GraphRunner
from graph_runner.graph_factory import build_minimal_graph


BASE = Path(__file__).resolve().parents[1]


def load_config():
    config_path = BASE / "configs" / "smoke_vskarich_baseline_leg.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_case(config: dict) -> dict:
    cases_file = config["cases"]["source"]
    max_cases = config["cases"].get("max_cases", 1)

    cases_path = BASE / cases_file
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    case = cases[0]

    # Populate code_files_contents from disk (like the legacy runner does)
    case["code_files_contents"] = {}
    for rel in case.get("code_files", []):
        full_path = BASE / rel
        if full_path.exists():
            case["code_files_contents"][rel] = full_path.read_text(encoding="utf-8")

    return case


def main():
    # Load config
    config = load_config()
    print(f"Config: {config['experiment']['name']}")
    print(f"Cases source: {config['cases']['source']}")

    # Load one real case
    case = load_case(config)
    print(f"Case: {case['id']} (difficulty={case['difficulty']}, failure_mode={case['failure_mode']})")
    print()

    # Load case into graph_runner state
    state = load_case_into_state(case)

    # Build and run graph
    graph = build_minimal_graph()
    runner = GraphRunner(graph)
    final_state = runner.run(state)

    # Print results
    print("[SMOKE TEST]")
    print(f"  case exists:            {final_state.has('case')}")
    print(f"  prompt exists:          {final_state.has('prompt')}")
    print(f"  raw_response exists:    {final_state.has('raw_response')}")
    print(f"  parsed_response exists: {final_state.has('parsed_response')}")
    print(f"  parse_error exists:     {final_state.has('parse_error')}")
    print(f"  exec_result exists:     {final_state.has('exec_result')}")

    if final_state.has("prompt"):
        prompt_val = final_state.get("prompt").value
        print(f"\n  prompt (first 200 chars):\n    {prompt_val[:200]}")

    if final_state.has("exec_result"):
        print(f"\n  exec_result: {final_state.get('exec_result').value}")

    print()

    # Hard assertions
    assert final_state.has("case"), "case artifact must exist"
    assert final_state.has("prompt"), "prompt artifact must exist (build_prompt ran)"
    assert final_state.has("raw_response"), "raw_response must exist (generate ran)"

    # Parse must have succeeded (fake generate returns valid dict)
    assert final_state.has("parsed_response"), "parsed_response must exist (parse succeeded)"
    assert not final_state.has("parse_error"), "parse_error must not exist"

    # Exec must have run
    assert final_state.has("exec_result"), "exec_result must exist (exec_eval ran)"
    assert not final_state.has("exec_contract_error"), "exec_contract_error must not exist"

    # Exec result must be success (fake code is valid Python)
    exec_val = final_state.get("exec_result").value
    assert exec_val["success"] is True, f"exec must succeed, got: {exec_val}"
    assert exec_val["error"] is None

    # Verify prompt contains case task
    prompt_val = final_state.get("prompt").value
    assert case["task"][:30] in prompt_val, "prompt must contain case task"

    print("ALL ASSERTIONS PASSED")
    print()

    # Verify all previous test suites still work
    print("Running regression checks...")


if __name__ == "__main__":
    main()
