"""Tests for easy calibration cases and reasoning interface conditions.

Validates:
  1. Reference code passes all 4 easy case invariants
  2. Simple mutations break the invariants
  3. Reasoning interface conditions produce different prompts
  4. All 3 reasoning conditions execute without crashing
  5. Easy cases are registered and loadable
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

BASE = Path(__file__).resolve().parents[1]

EASY_IDS = ["easy_temporal", "easy_conservation", "easy_state_machine", "easy_aliasing"]


def _load_case(case_id):
    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        c["code_files_contents"] = {fp: (BASE / fp).read_text().strip() for fp in c["code_files"]}
    return [c for c in cases if c["id"] == case_id][0]


def _concat_ref(case):
    return "\n\n".join((BASE / fp).read_text().strip() for fp in case["code_files"])


def _wrap(code):
    return f"```python\n{code}\n```"


# ════════════════════════════════════════════════════════════
# 1. EASY CASES EXIST AND LOAD
# ════════════════════════════════════════════════════════════


def test_easy_cases_registered():
    cases = json.loads((BASE / "cases.json").read_text())
    ids = [c["id"] for c in cases]
    for eid in EASY_IDS:
        assert eid in ids, f"{eid} not in cases.json"


def test_easy_cases_have_difficulty_field():
    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        if c["id"] in EASY_IDS:
            assert c.get("difficulty") == "easy", f"{c['id']} missing difficulty=easy"


# ════════════════════════════════════════════════════════════
# 2. REFERENCE CODE PASSES INVARIANTS
# ════════════════════════════════════════════════════════════


def test_easy_temporal_reference_passes():
    from exec_eval import exec_evaluate

    case = _load_case("easy_temporal")
    r = exec_evaluate(case, _concat_ref(case))
    assert r["pass"], f"easy_temporal reference should pass: {r['reasons']}"


def test_easy_conservation_reference_passes():
    from exec_eval import exec_evaluate

    case = _load_case("easy_conservation")
    r = exec_evaluate(case, _concat_ref(case))
    assert r["pass"], f"easy_conservation reference should pass: {r['reasons']}"


def test_easy_state_machine_reference_passes():
    from exec_eval import exec_evaluate

    case = _load_case("easy_state_machine")
    r = exec_evaluate(case, _concat_ref(case))
    assert r["pass"], f"easy_state_machine reference should pass: {r['reasons']}"


def test_easy_aliasing_reference_passes():
    from exec_eval import exec_evaluate

    case = _load_case("easy_aliasing")
    r = exec_evaluate(case, _concat_ref(case))
    assert r["pass"], f"easy_aliasing reference should pass: {r['reasons']}"


# ════════════════════════════════════════════════════════════
# 3. MUTATIONS BREAK INVARIANTS
# ════════════════════════════════════════════════════════════


def test_easy_temporal_mutation_fails():
    """Remove logging → invariant fails."""
    from exec_eval import exec_evaluate

    case = _load_case("easy_temporal")
    broken = (
        "_log = []\n"
        "def update_value(store, key, value):\n"
        "    store[key] = value\n"  # no log append
        "def get_log(): return list(_log)\n"
        "def clear(): _log.clear()\n"
        "def process(key, value):\n"
        "    store = {}\n"
        "    clear()\n"
        "    update_value(store, key, value)\n"
        "    log = get_log()\n"
        "    return {'stored': store[key], 'logged': log[-1]['value'] if log else None}\n"
    )
    r = exec_evaluate(case, broken)
    assert not r["pass"], "removing log should fail"


def test_easy_conservation_mutation_fails():
    """Remove debit → total not conserved."""
    from exec_eval import exec_evaluate

    case = _load_case("easy_conservation")
    broken = (
        "def transfer(src, dst, amount):\n"
        "    dst['balance'] += amount\n"  # forgot src -= amount
        "def get_total(*accts): return sum(a['balance'] for a in accts)\n"
        "def move_funds(src, dst, amount):\n"
        "    total_before = get_total(src, dst)\n"
        "    transfer(src, dst, amount)\n"
        "    return {'transferred': amount, 'total_before': total_before, 'total_after': get_total(src, dst)}\n"
    )
    r = exec_evaluate(case, broken)
    assert not r["pass"], "missing debit should fail conservation"


def test_easy_state_machine_mutation_fails():
    """Remove guard → invalid transition succeeds."""
    from exec_eval import exec_evaluate

    case = _load_case("easy_state_machine")
    broken = (
        "def transition(item, new_status):\n"
        "    item['status'] = new_status\n"  # no guard
        "def submit_and_approve(item):\n"
        "    transition(item, 'submitted')\n"
        "    transition(item, 'approved')\n"
        "    return item['status']\n"
    )
    r = exec_evaluate(case, broken)
    assert not r["pass"], "removing guard should fail"


def test_easy_aliasing_mutation_fails():
    """Return copy instead of reference → mutation not visible."""
    from exec_eval import exec_evaluate

    case = _load_case("easy_aliasing")
    broken = (
        "_data = {'items': []}\n"
        "def get_items(): return list(_data['items'])\n"  # copy, not reference
        "def add_item(item): _data['items'].append(item)\n"
        "def reset(): _data['items'] = []\n"
        "def populate_and_read():\n"
        "    reset()\n"
        "    add_item('a')\n"
        "    add_item('b')\n"
        "    ref = get_items()\n"
        "    add_item('c')\n"
        "    return ref\n"
    )
    r = exec_evaluate(case, broken)
    assert not r["pass"], "returning copy should fail aliasing test"


# ════════════════════════════════════════════════════════════
# 4. REASONING INTERFACE CONDITIONS
# ════════════════════════════════════════════════════════════


def test_reasoning_conditions_registered():
    from runner import ALL_CONDITIONS, VALID_CONDITIONS

    for c in ["structured_reasoning", "free_form_reasoning", "branching_reasoning"]:
        assert c in ALL_CONDITIONS, f"{c} not in ALL_CONDITIONS"
        assert c in VALID_CONDITIONS


def test_reasoning_prompts_differ():
    from execution import build_prompt

    case = _load_case("easy_temporal")
    base, _ = build_prompt(case, "baseline")
    sr, _ = build_prompt(case, "structured_reasoning")
    ff, _ = build_prompt(case, "free_form_reasoning")
    br, _ = build_prompt(case, "branching_reasoning")
    # All should be longer than baseline
    assert len(sr) > len(base)
    assert len(ff) > len(base)
    assert len(br) > len(base)
    # All should differ from each other
    assert sr != ff
    assert ff != br
    assert sr != br


def test_structured_has_steps():
    from reasoning_prompts import build_structured_reasoning

    p = build_structured_reasoning("base")
    assert "Step 1" in p
    assert "Step 4" in p


def test_free_form_is_minimal():
    from reasoning_prompts import build_free_form_reasoning

    p = build_free_form_reasoning("base")
    assert "Step 1" not in p
    assert len(p) < len(build_free_form_reasoning("base")) + 200


def test_branching_has_two_approaches():
    from reasoning_prompts import build_branching_reasoning

    p = build_branching_reasoning("base")
    assert "APPROACH A" in p
    assert "APPROACH B" in p
    assert "EVALUATION" in p


# ════════════════════════════════════════════════════════════
# 5. REASONING CONDITIONS EXECUTE
# ════════════════════════════════════════════════════════════


def test_all_reasoning_conditions_run():
    from execution import run_single

    case = _load_case("easy_temporal")
    for cond in ["structured_reasoning", "free_form_reasoning", "branching_reasoning"]:
        cid, cn, ev = run_single(case, "gpt-4.1-nano", cond)
        assert "pass" in ev, f"{cond}: no pass field"
        assert "score" in ev, f"{cond}: no score field"


# ════════════════════════════════════════════════════════════
# RUNNER
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
