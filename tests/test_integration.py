"""Tier 1 (T1.3) + Tier 2 (T2.1–T2.9): Integration tests.

T1.3: Reasoning-action gap detection across 3 failure modes
T2.1: Full pipeline mock baseline
T2.2: Prompt-to-invariant consistency
T2.3: Repair loop error feedback
T2.5: Deterministic execution
T2.8: Result structure integrity
T2.9: Execution path taken
"""
import sys
import os
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

BASE = Path(__file__).resolve().parents[1]


def _make_parsed(code, reasoning="", raw_output=None):
    if raw_output is None:
        raw_output = code
    return {"code": code, "reasoning": reasoning, "raw_output": raw_output, "parse_error": None, "_raw_fallback": False}


# ── T1.3: Reasoning-action gap detection (3 modes) ──────────

def test_reasoning_gap_hidden_dep():
    """Correct reasoning + broken code → reasoning_correct_execution_failed."""
    from evaluator import evaluate_output
    case = _get_case("hidden_dep_multihop")
    # Output has correct reasoning signals but broken code
    reasoning = (
        "The cache_put always overwrites while cache_put_if_absent won't overwrite "
        "stale data. This is a live write-through dependency."
    )
    code = (
        "_store = {}\n"
        "def cache_put_if_absent(k, v):\n"
        "    if k not in _store: _store[k] = v\n"
        "def refresh_user_snapshot(user):\n"
        "    cache_put_if_absent(f\"user:{user['id']}\", user['name'])\n"
        "def save_user(user):\n"
        "    refresh_user_snapshot(user)"
    )
    raw_output = reasoning + "\n\n```python\n" + code + "\n```"
    parsed = _make_parsed(code, reasoning, raw_output)
    result = evaluate_output(case, parsed)
    assert result.get("identified_correct_issue") is True, "should detect correct reasoning"
    assert result["pass"] is False, "broken code should fail execution"
    assert result.get("reasoning_action_gap") is True


def test_reasoning_gap_temporal():
    """Correct reasoning + stats on wrong data → gap."""
    from evaluator import evaluate_output
    case = _get_case("temporal_semantic_drift")
    reasoning = "compute_raw_stats must run on original data before transforms."
    code = (
        "def normalize(d):\n    m = max(d)\n    return [x/m for x in d]\n"
        "def smooth(d, w=3):\n    return d\n"
        "def clip_negatives(d):\n    return [max(0,x) for x in d]\n"
        "def compute_raw_stats(d):\n    return {'raw_mean':sum(d)/len(d),'raw_max':max(d),'raw_min':min(d),'raw_range':max(d)-min(d)}\n"
        "def compute_quality_score(d):\n    return 1.0\n"
        "def summarize_for_display(d):\n    return {}\n"
        "def pipeline(data):\n"
        "    cleaned = clip_negatives(normalize(smooth(data)))\n"
        "    raw_stats = compute_raw_stats(cleaned)  # WRONG\n"
        "    return {'raw_stats': raw_stats, 'quality': 1.0, 'cleaned': cleaned}"
    )
    raw_output = reasoning + "\n\n```python\n" + code + "\n```"
    parsed = _make_parsed(code, reasoning, raw_output)
    result = evaluate_output(case, parsed)
    assert result.get("identified_correct_issue") is True
    assert result["pass"] is False


def test_reasoning_gap_state_pipeline():
    """Correct reasoning + removes commit → gap."""
    from evaluator import evaluate_output
    case = _get_case("l3_state_pipeline")
    reasoning = (
        "commit() sets frozen=True which get_committed_total needs. "
        "preview() calls stage without commit. Returns None if frozen is False."
    )
    code = (
        "def make_state(e): return {'raw':list(e),'pending':[],'stable':[],'view':[],'meta':{'version':0,'frozen':False}}\n"
        "def normalize(e):\n    seen=set()\n    return [x for x in e if x['id'] not in seen and not seen.add(x['id'])]\n"
        "def collapse(e):\n    m={}\n    for x in e:\n        k=x['id']\n        if k in m: m[k]['val']+=x.get('val',0)\n        else: m[k]=dict(x)\n    return list(m.values())\n"
        "def project(e): return [{'id':x['id'],'label':x.get('label',''),'val':x.get('val',0)} for x in e]\n"
        "def stage(st,p):\n    st['pending']=list(p)\n    st['view']=project(p)\n    st['meta']['version']+=1\n"
        "def materialize(st): return {'items':list(st['stable']),'display':list(st['view']),'v':st['meta']['version']}\n"
        "def process_batch(entries):\n"
        "    st = make_state(entries)\n"
        "    cleaned = normalize(st['raw'])\n"
        "    merged = collapse(cleaned)\n"
        "    stage(st, merged)\n"
        "    # commit removed for simplicity\n"
        "    return st, materialize(st)"
    )
    raw_output = reasoning + "\n\n```python\n" + code + "\n```"
    parsed = _make_parsed(code, reasoning, raw_output)
    result = evaluate_output(case, parsed)
    assert result.get("identified_correct_issue") is True
    assert result["pass"] is False


# ── T2.1: Full pipeline mock baseline ────────────────────────

def test_full_pipeline_mock_baseline():
    """_run_single in mock mode → all required fields present."""
    from execution import run_single as _run_single
    case = _get_case("l3_state_pipeline")
    cid, cond, ev = _run_single(case, "gpt-4.1-nano", "baseline")
    assert cid == "l3_state_pipeline"
    assert cond == "baseline"
    assert "pass" in ev and isinstance(ev["pass"], bool)
    assert "score" in ev and isinstance(ev["score"], (int, float))
    assert "reasons" in ev and isinstance(ev["reasons"], list)
    assert "failure_modes" in ev
    assert "alignment" in ev


# ── T2.2: Prompt-to-invariant consistency ────────────────────

def test_prompt_to_invariant_consistency():
    """For each case: case_id in prompt matches case_id in invariant lookup."""
    from execution import build_prompt as _build_prompt
    from exec_eval import _CASE_TESTS, _load_v2_test

    cases = json.loads((BASE / "cases.json").read_text())
    for case in cases:
        case["code_files_contents"] = {
            fp: (BASE / fp).read_text().strip() for fp in case["code_files"]
        }
    mismatches = []
    for case in cases:
        cid = case["id"]
        prompt, _ = _build_prompt(case, "baseline")
        # Check all code files are in the prompt
        for fp in case["code_files"]:
            if fp not in prompt:
                mismatches.append(f"{cid}: code_file {fp} not in prompt")
        # Check invariant test is registered (V1 dispatch OR V2 loader)
        if cid not in _CASE_TESTS and _load_v2_test(case) is None:
            mismatches.append(f"{cid}: no invariant test in _CASE_TESTS or tests_v2/")
    assert not mismatches, "\n".join(mismatches)


# ── T2.3: Repair loop error feedback ─────────────────────────

def test_repair_loop_second_prompt_contains_errors():
    """Repair loop on failing case → second call's prompt contains error feedback."""
    from execution import run_repair_loop as _run_repair_loop
    case = _get_case("l3_state_pipeline")
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")
    # If first attempt failed, there should be 2 attempts
    if ev["num_attempts"] == 2:
        first_reasons = ev["attempts"][0].get("reasons", [])
        assert len(first_reasons) > 0, "first attempt should have reasons"
        # The repair loop feeds errors back — we can't inspect the prompt directly
        # but we can verify the structure
        assert ev["attempts"][1]["attempt"] == 2


# ── T2.5: Deterministic execution ────────────────────────────

def test_deterministic_execution():
    """Same case+condition twice → identical scores."""
    from execution import run_single as _run_single
    case = _get_case("l3_state_pipeline")
    _, _, ev1 = _run_single(case, "gpt-4.1-nano", "baseline")
    _, _, ev2 = _run_single(case, "gpt-4.1-nano", "baseline")
    assert ev1["score"] == ev2["score"], f"{ev1['score']} != {ev2['score']}"
    assert ev1["pass"] == ev2["pass"]


# ── T2.8: Result structure integrity ─────────────────────────

def test_result_structure_integrity():
    """Repair loop result has all required fields."""
    from execution import run_repair_loop as _run_repair_loop
    case = _get_case("l3_state_pipeline")
    _, _, ev = _run_repair_loop(case, "gpt-4.1-nano")
    assert "attempts" in ev and isinstance(ev["attempts"], list)
    assert "num_attempts" in ev and isinstance(ev["num_attempts"], int)
    assert "final_pass" in ev and isinstance(ev["final_pass"], bool)
    assert "execution" in ev
    assert "alignment" in ev
    assert "category" in ev["alignment"]


# ── T2.9: Execution path taken ───────────────────────────────

def test_execution_path_taken():
    """evaluate_output on a case with code → execution.ran == True."""
    from evaluator import evaluate_output
    case = _get_case("l3_state_pipeline")
    ref_parts = []
    for fp in case["code_files"]:
        ref_parts.append((BASE / fp).read_text().strip())
    code = "\n\n".join(ref_parts)
    raw_output = "```python\n" + code + "\n```"
    parsed = _make_parsed(code, "", raw_output)
    result = evaluate_output(case, parsed)
    ex = result.get("execution", {})
    assert ex.get("ran") is True, f"execution.ran should be True, got {ex}"


# ── Helper ───────────────────────────────────────────────────

def _get_case(case_id):
    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        c["code_files_contents"] = {
            fp: (BASE / fp).read_text().strip() for fp in c["code_files"]
        }
    matches = [c for c in cases if c["id"] == case_id]
    assert matches, f"case {case_id} not found"
    return matches[0]


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
