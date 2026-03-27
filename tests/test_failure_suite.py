"""Deliberate failure test suite.

Validates that the system correctly FAILS when it should:
  - execution runs (not skipped)
  - broken code fails invariants
  - reasoning-action gaps detected
  - invariants are meaningful (mutations break them)
  - parser handles messy output
  - runtime errors surfaced
  - results are structured and deterministic
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

BASE = Path(__file__).resolve().parents[1]


def _load_case(case_id):
    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        c["code_files_contents"] = {fp: (BASE / fp).read_text().strip() for fp in c["code_files"]}
    return [c for c in cases if c["id"] == case_id][0]


def _concat_ref(case):
    return "\n\n".join((BASE / fp).read_text().strip() for fp in case["code_files"])


def _wrap(code):
    return f"```python\n{code}\n```"


def _make_parsed(code, reasoning="", raw_output=None):
    if raw_output is None:
        raw_output = code
    return {
        "code": code,
        "reasoning": reasoning,
        "raw_output": raw_output,
        "parse_error": None,
        "_raw_fallback": False,
    }


# ════════════════════════════════════════════════════════════
# 1. EXECUTION ENFORCEMENT
# ════════════════════════════════════════════════════════════


def test_execution_is_not_skipped():
    """evaluate_output MUST actually execute code, not just pattern-match."""
    from evaluator import evaluate_output

    case = _load_case("l3_state_pipeline")
    ref = _concat_ref(case)
    parsed = _make_parsed(ref, raw_output=_wrap(ref))
    result = evaluate_output(case, parsed)
    assert result["execution"]["ran"] is True, "execution was skipped"


def test_execution_runs_on_every_case():
    """Every case with reference code triggers real execution."""
    from evaluator import evaluate_output

    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        c["code_files_contents"] = {fp: (BASE / fp).read_text().strip() for fp in c["code_files"]}
        ref = _concat_ref(c)
        parsed = _make_parsed(ref, raw_output=_wrap(ref))
        result = evaluate_output(c, parsed)
        assert result.get("execution", {}).get("ran") is True, f"{c['id']}: execution not ran"


# ════════════════════════════════════════════════════════════
# 2. FALSE POSITIVE REJECTION
# ════════════════════════════════════════════════════════════


def test_false_positive_state_pipeline():
    """Code that looks clean but removes commit() must FAIL."""
    from evaluator import evaluate_output

    case = _load_case("l3_state_pipeline")
    reasoning = "Simplified the pipeline by removing redundant steps."
    code = (
        "def make_state(e): return {'raw':list(e),'pending':[],'stable':[],'view':[],'meta':{'version':0,'frozen':False}}\n"
        "def normalize(e):\n    seen=set()\n    return [x for x in e if x['id'] not in seen and not seen.add(x['id'])]\n"
        "def collapse(e):\n    m={}\n    for x in e:\n        k=x['id']\n        if k in m: m[k]['val']+=x.get('val',0)\n        else: m[k]=dict(x)\n    return list(m.values())\n"
        "def project(e): return [{'id':x['id'],'label':x.get('label',''),'val':x.get('val',0)} for x in e]\n"
        "def stage(st,p):\n    st['pending']=list(p)\n    st['view']=project(p)\n    st['meta']['version']+=1\n"
        "def materialize(st): return {'items':list(st['stable']),'display':list(st['view']),'v':st['meta']['version']}\n"
        "def process_batch(entries):\n"
        "    st = make_state(entries)\n"
        "    merged = collapse(normalize(st['raw']))\n"
        "    stage(st, merged)\n"
        "    return st, materialize(st)\n"
    )
    raw_output = reasoning + "\n\n" + _wrap(code)
    parsed = _make_parsed(code, reasoning=reasoning, raw_output=raw_output)
    result = evaluate_output(case, parsed)
    assert result["pass"] is False, "false positive: missing commit() not caught"
    assert result["execution"]["status"] == "failed"


def test_false_positive_temporal():
    """Stats computed on cleaned data must FAIL (looks plausible, semantically wrong)."""
    from evaluator import evaluate_output

    case = _load_case("temporal_semantic_drift")
    code = (
        "def normalize(d):\n    m=max(d)\n    return [x/m for x in d]\n"
        "def clip_negatives(d): return [max(0,x) for x in d]\n"
        "def smooth(d,w=3):\n    r=[]\n    for i in range(len(d)):\n        s=max(0,i-w+1)\n        r.append(sum(d[s:i+1])/(i-s+1))\n    return r\n"
        "def compute_raw_stats(d): return {'raw_mean':sum(d)/len(d),'raw_max':max(d),'raw_min':min(d),'raw_range':max(d)-min(d)}\n"
        "def compute_quality_score(d):\n    z=sum(1 for x in d if x==0)\n    return 1.0-(z/len(d)) if d else 0.0\n"
        "def summarize_for_display(d): return {'avg':round(sum(d)/len(d),1)}\n"
        "def pipeline(data):\n"
        "    cleaned = clip_negatives(normalize(smooth(data)))\n"
        "    raw_stats = compute_raw_stats(cleaned)\n"  # BUG: should be data
        "    return {'raw_stats': raw_stats, 'quality': compute_quality_score(cleaned), 'cleaned': cleaned}\n"
    )
    parsed = _make_parsed(code, raw_output=_wrap(code))
    result = evaluate_output(case, parsed)
    assert result["pass"] is False, "stats on cleaned data should fail"


# ════════════════════════════════════════════════════════════
# 3. REASONING-ACTION GAP (3 cases)
# ════════════════════════════════════════════════════════════


def test_gap_hidden_dependency():
    """Correct reasoning ('always overwrite', 'stale') + wrong code → gap."""
    from evaluator import evaluate_output

    case = _load_case("hidden_dep_multihop")
    reasoning = (
        "sync_user_to_cache always overwrites via cache_put. "
        "cache_put_if_absent won't overwrite — stale data would remain."
    )
    code = (
        "_store = {}\n"
        "def cache_put_if_absent(k,v):\n    if k not in _store: _store[k]=v\n"
        "def save_user(u): cache_put_if_absent(f\"user:{u['id']}\", u['name'])\n"
    )
    raw_output = reasoning + "\n\n" + _wrap(code)
    parsed = _make_parsed(code, reasoning=reasoning, raw_output=raw_output)
    r = evaluate_output(case, parsed)
    assert r["identified_correct_issue"] is True, "should detect correct reasoning"
    assert r["pass"] is False, "broken code should fail"
    assert r["reasoning_action_gap"] is True, "gap not detected"


def test_gap_temporal_ordering():
    """Correct reasoning ('original data') + stats on wrong data → gap."""
    from evaluator import evaluate_output

    case = _load_case("temporal_semantic_drift")
    reasoning = "compute_raw_stats must use original data, not normalized."
    code = (
        "def normalize(d):\n    m=max(d)\n    return [x/m for x in d]\n"
        "def smooth(d,w=3): return d\n"
        "def clip_negatives(d): return [max(0,x) for x in d]\n"
        "def compute_raw_stats(d): return {'raw_mean':sum(d)/len(d),'raw_max':max(d),'raw_min':min(d),'raw_range':max(d)-min(d)}\n"
        "def compute_quality_score(d): return 1.0\n"
        "def summarize_for_display(d): return {}\n"
        "def pipeline(data):\n"
        "    c = clip_negatives(normalize(smooth(data)))\n"
        "    return {'raw_stats': compute_raw_stats(c), 'quality': 1.0, 'cleaned': c}\n"
    )
    raw_output = reasoning + "\n\n" + _wrap(code)
    parsed = _make_parsed(code, reasoning=reasoning, raw_output=raw_output)
    r = evaluate_output(case, parsed)
    assert r["identified_correct_issue"] is True
    assert r["pass"] is False
    assert r["reasoning_action_gap"] is True


def test_gap_state_pipeline():
    """Mentions 'frozen', 'get_committed_total' + removes commit → gap."""
    from evaluator import evaluate_output

    case = _load_case("l3_state_pipeline")
    reasoning = "commit() sets frozen=True. get_committed_total returns None when frozen is False."
    code = (
        "def make_state(e): return {'raw':list(e),'pending':[],'stable':[],'view':[],'meta':{'version':0,'frozen':False}}\n"
        "def normalize(e):\n    s=set()\n    return [x for x in e if x['id'] not in s and not s.add(x['id'])]\n"
        "def collapse(e):\n    m={}\n    for x in e:\n        k=x['id']\n        if k in m: m[k]['val']+=x.get('val',0)\n        else: m[k]=dict(x)\n    return list(m.values())\n"
        "def project(e): return [{'id':x['id'],'label':x.get('label',''),'val':x.get('val',0)} for x in e]\n"
        "def stage(st,p):\n    st['pending']=list(p)\n    st['view']=project(p)\n    st['meta']['version']+=1\n"
        "def materialize(st): return {'items':list(st['stable']),'display':list(st['view']),'v':st['meta']['version']}\n"
        "def process_batch(entries):\n"
        "    st=make_state(entries)\n"
        "    stage(st, collapse(normalize(st['raw'])))\n"
        "    return st, materialize(st)\n"
    )
    raw_output = reasoning + "\n\n" + _wrap(code)
    parsed = _make_parsed(code, reasoning=reasoning, raw_output=raw_output)
    r = evaluate_output(case, parsed)
    assert r["identified_correct_issue"] is True
    assert r["pass"] is False
    assert r["reasoning_action_gap"] is True


# ════════════════════════════════════════════════════════════
# 4. INVARIANT STRENGTH (MUTATIONS)
# ════════════════════════════════════════════════════════════


def test_mutation_remove_commit():
    """Removing commit(st) from reference code must be caught."""
    from exec_eval import exec_evaluate

    case = _load_case("l3_state_pipeline")
    ref = _concat_ref(case)
    mutated = ref.replace("    commit(st)\n", "")
    r = exec_evaluate(case, mutated)
    assert r["pass"] is False, "removing commit should fail frozen gate"


def test_mutation_swap_cache_semantics():
    """Changing cache_put to cache_put_if_absent breaks overwrite on re-save."""
    from exec_eval import load_module_from_code, _load_v2_test
    from parse import strip_local_imports

    case = _load_case("hidden_dep_multihop")
    test_fn = _load_v2_test(case)
    assert test_fn is not None, "No test function for hidden_dep_multihop"
    ref = _concat_ref(case)
    mutated = ref.replace(
        'def sync_user_to_cache(user):\n    cache_put(f"user:{user[\'id\']}", user["name"])',
        'def sync_user_to_cache(user):\n    cache_put_if_absent(f"user:{user[\'id\']}", user["name"])',
    )
    mod = load_module_from_code(strip_local_imports(mutated), "mut_cache")
    passed, _ = test_fn(mod)
    assert not passed, "put_if_absent should fail on re-save"


def test_mutation_reorder_stats():
    """Moving compute_raw_stats after normalize must be caught."""
    from exec_eval import exec_evaluate

    case = _load_case("temporal_semantic_drift")
    ref = _concat_ref(case)
    # Move raw_stats after transforms
    mutated = ref.replace(
        "    raw_stats = compute_raw_stats(data)",
        "    # raw_stats moved below",
    ).replace(
        "    quality = compute_quality_score(cleaned)",
        "    raw_stats = compute_raw_stats(cleaned)\n    quality = compute_quality_score(cleaned)",
    )
    r = exec_evaluate(case, mutated)
    assert r["pass"] is False, "stats on cleaned data should fail"


# ════════════════════════════════════════════════════════════
# 5. RUNTIME ERROR HANDLING
# ════════════════════════════════════════════════════════════


def test_runtime_error_surfaced():
    """Code that raises during invariant test → error status, not silent pass."""
    from exec_eval import exec_evaluate

    case = _load_case("l3_state_pipeline")
    crashing = _wrap(
        "def make_state(e): raise RuntimeError('test crash')\n"
        "def process_batch(entries): return make_state(entries), {}\n"
    )
    r = exec_evaluate(case, crashing)
    assert r["pass"] is False
    ex = r["execution"]
    # Must indicate error, not silent success
    assert ex.get("status") == "error" or ex.get("invariant_pass") is False


def test_syntax_error_surfaced():
    """Syntactically invalid code → clear error."""
    from exec_eval import exec_evaluate

    case = _load_case("l3_state_pipeline")
    r = exec_evaluate(case, "def f(:\n    pass")
    assert r["pass"] is False
    assert r["execution"]["syntax_error"] is not None


# ════════════════════════════════════════════════════════════
# 6. PARSER ROBUSTNESS
# ════════════════════════════════════════════════════════════


def test_parser_no_code_block():
    """Plain text with no code fences → code extracted from raw."""
    from parse import parse_model_response

    r = parse_model_response("def hello(): return 42")
    assert r["code"] is not None
    assert len(r["code"]) > 0
    assert r["parse_error"] is not None


def test_parser_multiple_blocks_selects_last():
    """When multiple python blocks exist, use the LAST one."""
    from parse import extract_code

    text = (
        "First try:\n```python\nresult = 'wrong'\n```\n"
        "Better:\n```python\nresult = 'correct'\n```\n"
    )
    code = extract_code(text)
    assert "correct" in code
    assert "wrong" not in code


def test_parser_malformed_json():
    """Broken JSON must not crash — returns parse_error."""
    from parse import parse_model_response

    r = parse_model_response('{"reasoning": "x", "code":')
    assert r["parse_error"] is not None


def test_parser_mixed_text_and_code():
    """Reasoning text + code block → both extracted."""
    from parse import parse_model_response

    text = "The issue is the frozen flag.\n\n```python\ndef f(): return 1\n```\nDone."
    r = parse_model_response(text)
    assert "return 1" in r["code"]
    assert "frozen" in r["reasoning"]


def test_parser_json_valid():
    """Valid JSON response → clean extraction, no parse error."""
    from parse import parse_model_response

    r = parse_model_response('{"reasoning": "ok", "code": "x = 1"}')
    assert r["code"] == "x = 1"
    assert r["parse_error"] is None


# ════════════════════════════════════════════════════════════
# 7. RESULT STRUCTURE
# ════════════════════════════════════════════════════════════


def test_result_has_execution_fields():
    """Every evaluation result must have structured execution info."""
    from evaluator import evaluate_output

    case = _load_case("l3_state_pipeline")
    ref = _concat_ref(case)
    parsed = _make_parsed(ref, raw_output=_wrap(ref))
    r = evaluate_output(case, parsed)
    assert "execution" in r
    assert "status" in r["execution"]
    assert r["execution"]["status"] in ("passed", "failed", "error")


def test_result_has_alignment():
    """Every evaluation result must have alignment classification."""
    from evaluator import evaluate_output

    case = _load_case("l3_state_pipeline")
    ref = _concat_ref(case)
    parsed = _make_parsed(ref, raw_output=_wrap(ref))
    r = evaluate_output(case, parsed)
    assert "identified_correct_issue" in r
    assert "reasoning_action_gap" in r
    assert isinstance(r["reasoning_action_gap"], bool)


# ════════════════════════════════════════════════════════════
# 8. DETERMINISM
# ════════════════════════════════════════════════════════════


def test_deterministic_same_input():
    """Same case + same output → identical scores."""
    from evaluator import evaluate_output

    case = _load_case("l3_state_pipeline")
    ref = _concat_ref(case)
    parsed = _make_parsed(ref, raw_output=_wrap(ref))
    r1 = evaluate_output(case, parsed)
    r2 = evaluate_output(case, parsed)
    assert r1["pass"] == r2["pass"]
    assert r1["score"] == r2["score"]
    assert r1["execution"]["status"] == r2["execution"]["status"]


# ════════════════════════════════════════════════════════════
# 9. FULL PIPELINE
# ════════════════════════════════════════════════════════════


def test_full_pipeline_baseline():
    """Full pipeline (mock LLM) produces structured result."""
    from execution import run_single

    case = _load_case("l3_state_pipeline")
    cid, cond, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert cid == "l3_state_pipeline"
    assert cond == "baseline"
    assert isinstance(ev["pass"], bool)
    assert isinstance(ev["score"], (int, float))
    assert "execution" in ev
    assert ev["execution"]["ran"] is True


# ════════════════════════════════════════════════════════════
# 10. ALL CONDITIONS EXECUTE
# ════════════════════════════════════════════════════════════


def test_all_conditions_no_crash():
    """Every condition runs without exception on one case."""
    from runner import ALL_CONDITIONS
    from execution import run_single, run_repair_loop

    case = _load_case("l3_state_pipeline")
    scores = {}
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
            _, _, ev = run_repair_loop(case, "gpt-4.1-nano")
        elif cond in _SPECIAL_CONDITIONS:
            from runner import _run_one

            _, _, ev = _run_one(case, "gpt-4.1-nano", cond)
        else:
            _, _, ev = run_single(case, "gpt-4.1-nano", cond)
        assert "pass" in ev, f"{cond}: no 'pass' field"
        assert "score" in ev, f"{cond}: no 'score' field"
        scores[cond] = ev["score"]
    assert len(scores) == len(ALL_CONDITIONS)


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
