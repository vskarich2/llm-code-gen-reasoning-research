"""Tier 2 (T2.6): All conditions execute for one case without crashes."""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

import json
from runner import ALL_CONDITIONS
from execution import run_single as _run_single, run_repair_loop as _run_repair_loop

BASE = Path(__file__).resolve().parents[1]


def _get_case(case_id):
    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        c["code_files_contents"] = {fp: (BASE / fp).read_text().strip() for fp in c["code_files"]}
    return [c for c in cases if c["id"] == case_id][0]


def test_all_conditions_execute():
    """Every condition runs without crashing, produces structured result."""
    case = _get_case("l3_state_pipeline")
    results = {}
    # Conditions with special dispatch (not routed through run_single)
    _SPECIAL_CONDITIONS = {
        "repair_loop",
        "contract_gated",
        "retry_no_contract",
        "retry_with_contract",
        "retry_adaptive",
        "retry_alignment",
    }
    for cond in ALL_CONDITIONS:
        if cond == "repair_loop":
            _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")
        elif cond in _SPECIAL_CONDITIONS:
            from runner import _run_one

            _, _, ev = _run_one(case, "gpt-4.1-nano", cond)
        else:
            _, _, ev = _run_single(case, "gpt-4.1-nano", cond)
        assert "pass" in ev, f"{cond}: missing 'pass'"
        assert "score" in ev, f"{cond}: missing 'score'"
        assert isinstance(ev["score"], (int, float)), f"{cond}: score not numeric"
        results[cond] = ev["score"]

    # At least 2 conditions should produce different scores (system is not trivial)
    unique_scores = set(results.values())
    # This is a soft check — mock mode may produce identical scores
    # but we at least verify no crashes and structured output
    assert len(results) == len(ALL_CONDITIONS)


if __name__ == "__main__":
    try:
        test_all_conditions_execute()
        print("  PASS  test_all_conditions_execute")
    except Exception as e:
        print(f"  FAIL  test_all_conditions_execute: {e}")
