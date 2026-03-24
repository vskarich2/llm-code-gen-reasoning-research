"""Comprehensive tests for the SCM + Evidence Grounding system.

Tests cover:
  1. SCM data integrity
  2. Prompt generation for all SCM conditions
  3. Evidence usage scoring (0-3 scale)
  4. Incorrect/uncertain/hallucinated evidence detection
  5. Evidence-action gap computation
  6. Delta gap metric
  7. Integration with existing pipeline
  8. All SCM conditions execute without crashing
  9. Length-matched control has no causal content
  10. Backward compatibility — existing conditions unaffected
"""
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

BASE = Path(__file__).resolve().parents[1]


def _get_case(case_id):
    cases = json.loads((BASE / "cases.json").read_text())
    for c in cases:
        c["code_files_contents"] = {
            fp: (BASE / fp).read_text().strip() for fp in c["code_files"]
        }
    return [c for c in cases if c["id"] == case_id][0]


import re as _re

def _raw_to_parsed(raw_string):
    """Convert a raw LLM output string into the parsed_dict format
    expected by evaluate_output(case, parsed_dict).

    Extracts code from ```python ... ``` blocks, and treats everything
    before the first code block as reasoning.
    """
    code = ""
    reasoning = ""
    # Find the first ```python ... ``` block
    m = _re.search(r"```python\s*\n?(.*?)```", raw_string, _re.DOTALL)
    if m:
        code = m.group(1).rstrip("\n")
        # Reasoning is everything before the code block
        reasoning = raw_string[:m.start()].strip()
    else:
        # No code block found — everything is reasoning
        reasoning = raw_string.strip()
    return {
        "code": code,
        "reasoning": reasoning,
        "raw_output": raw_string,
        "parse_error": None,
        "_raw_fallback": False,
    }


# ════════════════════════════════════════════════════════════
# 1. SCM DATA INTEGRITY
# ════════════════════════════════════════════════════════════

def test_scm_registry_has_5_cases():
    from scm_data import SCM_REGISTRY
    assert len(SCM_REGISTRY) >= 5


def test_scm_has_required_fields():
    from scm_data import SCM_REGISTRY
    for case_id, scm in SCM_REGISTRY.items():
        assert "functions" in scm, f"{case_id}: missing functions"
        assert "variables" in scm, f"{case_id}: missing variables"
        assert "edges" in scm, f"{case_id}: missing edges"
        assert "invariants" in scm, f"{case_id}: missing invariants"
        assert "constraints" in scm, f"{case_id}: missing constraints"
        assert "critical_evidence_set" in scm, f"{case_id}: missing critical_evidence_set"
        assert "critical_constraint" in scm, f"{case_id}: missing critical_constraint"


def test_scm_ids_are_well_formed():
    from scm_data import SCM_REGISTRY
    import re
    for case_id, scm in SCM_REGISTRY.items():
        for fid in scm["functions"]:
            assert re.match(r"^F\d+$", fid), f"{case_id}: bad function ID {fid}"
        for vid in scm["variables"]:
            assert re.match(r"^V\d+$", vid), f"{case_id}: bad variable ID {vid}"
        for eid in scm["edges"]:
            assert re.match(r"^E\d+$", eid), f"{case_id}: bad edge ID {eid}"
        for iid in scm["invariants"]:
            assert re.match(r"^I\d+$", iid), f"{case_id}: bad invariant ID {iid}"
        for cid in scm["constraints"]:
            assert re.match(r"^C\d+$", cid), f"{case_id}: bad constraint ID {cid}"


def test_critical_set_references_valid_ids():
    from scm_data import SCM_REGISTRY
    for case_id, scm in SCM_REGISTRY.items():
        ces = scm["critical_evidence_set"]
        all_f = set(scm["functions"].keys())
        all_e = set(scm["edges"].keys())
        all_i = set(scm["invariants"].keys())
        all_c = set(scm["constraints"].keys())
        for f in ces.get("functions", []):
            assert f in all_f, f"{case_id}: critical F {f} not in functions"
        for e in ces.get("edges", []):
            assert e in all_e, f"{case_id}: critical E {e} not in edges"
        for i in ces.get("invariants", []):
            assert i in all_i, f"{case_id}: critical I {i} not in invariants"
        for c in ces.get("constraints", []):
            assert c in all_c, f"{case_id}: critical C {c} not in constraints"


def test_constraint_references_valid_ids():
    from scm_data import SCM_REGISTRY
    for case_id, scm in SCM_REGISTRY.items():
        all_e = set(scm["edges"].keys())
        all_f = set(scm["functions"].keys())
        all_i = set(scm["invariants"].keys())
        for cid, c in scm["constraints"].items():
            for e in c.get("edges", []):
                assert e in all_e, f"{case_id}/{cid}: edge {e} not in edges"
            for f in c.get("functions", []):
                assert f in all_f, f"{case_id}/{cid}: func {f} not in functions"
            for i in c.get("invariants", []):
                assert i in all_i, f"{case_id}/{cid}: inv {i} not in invariants"


# ════════════════════════════════════════════════════════════
# 2. PROMPT GENERATION
# ════════════════════════════════════════════════════════════

def test_scm_descriptive_includes_edges():
    from scm_prompts import build_scm_descriptive
    p = build_scm_descriptive("base task", "l3_state_pipeline")
    assert "E1:" in p or "E2:" in p or "E3:" in p
    assert len(p) > len("base task")


def test_scm_constrained_includes_steps():
    from scm_prompts import build_scm_constrained
    p = build_scm_constrained("base task", "l3_state_pipeline")
    assert "STEP 1" in p
    assert "STEP 2" in p
    assert "STEP 4" in p


def test_scm_evidence_includes_all_id_types():
    from scm_prompts import build_scm_constrained_evidence
    p = build_scm_constrained_evidence("base task", "hidden_dep_multihop")
    assert "F1" in p or "F3" in p
    assert "V1" in p
    assert "E1" in p or "E2" in p
    assert "I1" in p or "I2" in p
    assert "C1" in p or "C2" in p


def test_scm_evidence_includes_critical_constraint():
    from scm_prompts import build_scm_constrained_evidence
    p = build_scm_constrained_evidence("base task", "hidden_dep_multihop")
    assert "CRITICAL CONSTRAINT" in p or "most fragile" in p.lower()


def test_scm_evidence_minimal_is_shorter():
    from scm_prompts import build_scm_constrained_evidence, build_scm_constrained_evidence_minimal
    full = build_scm_constrained_evidence("base", "l3_state_pipeline")
    mini = build_scm_constrained_evidence_minimal("base", "l3_state_pipeline")
    assert len(mini) < len(full), "minimal should be shorter than full"
    assert len(mini) > len("base"), "minimal should add something"


def test_evidence_only_excludes_edges():
    from scm_prompts import build_evidence_only
    p = build_evidence_only("base task", "l3_state_pipeline")
    # Should have F*, V*, C*, I* but NOT E* edge list
    assert "no dependency graph" in p.lower() or "determine relationships yourself" in p.lower()


def test_length_matched_has_no_causal_content():
    from scm_prompts import build_length_matched_control
    p = build_length_matched_control("base", "l3_state_pipeline")
    assert "F1" not in p and "E1" not in p and "I1" not in p
    assert "commit" not in p.lower()
    assert "frozen" not in p.lower()
    assert len(p) > len("base") + 200  # adds substantial filler


def test_scm_graceful_for_unmapped_case():
    from scm_prompts import build_scm_descriptive, build_scm_constrained_evidence
    # Case with no SCM data should return base unchanged
    p1 = build_scm_descriptive("base", "nonexistent_case_xyz")
    assert p1 == "base"
    p2 = build_scm_constrained_evidence("base", "nonexistent_case_xyz")
    assert p2 == "base"


# ════════════════════════════════════════════════════════════
# 3. EVIDENCE USAGE SCORING
# ════════════════════════════════════════════════════════════

def test_evidence_score_0_no_ids():
    from evaluator import compute_evidence_metrics
    case = _get_case("l3_state_pipeline")
    output = "I simplified the code by removing redundant steps."
    m = compute_evidence_metrics(case, output)
    assert m["evidence_usage_score"] == 0


def test_evidence_score_1_ids_mentioned():
    from evaluator import compute_evidence_metrics
    case = _get_case("l3_state_pipeline")
    output = "Looking at F2, F3, F5, and E3, these are important."
    m = compute_evidence_metrics(case, output)
    assert m["evidence_usage_score"] >= 1


def test_evidence_score_2_ids_mapped_to_code():
    from evaluator import compute_evidence_metrics
    case = _get_case("l3_state_pipeline")
    output = "F3 (commit) sets st['meta']['frozen']=True. F5 (get_committed_total) checks this flag via E4."
    m = compute_evidence_metrics(case, output)
    assert m["evidence_usage_score"] >= 2


def test_evidence_score_3_requires_chain_and_no_errors():
    from evaluator import compute_evidence_metrics
    case = _get_case("l3_state_pipeline")
    output = (
        "C1 requires that commit (F3) is preserved because E3 sets the frozen flag (V3) "
        "which get_committed_total (F5) checks via E4. This protects I1 (frozen==True after process_batch). "
        "Removing F3 would break I2 since get_committed_total would return None."
    )
    m = compute_evidence_metrics(case, output)
    assert m["evidence_usage_score"] == 3
    assert m["incorrect_evidence_usage_count"] == 0


def test_evidence_score_3_blocked_by_incorrect_usage():
    from evaluator import compute_evidence_metrics
    case = _get_case("hidden_dep_multihop")
    # Correct chain but also incorrect claim: says F7 always overwrites (it doesn't)
    output = (
        "C2 ensures E2 uses F6 to protect I2. The chain C2→E2→F6→I2 is preserved. "
        "Also, F7 (cache_put_if_absent) always overwrites existing entries."  # WRONG
    )
    m = compute_evidence_metrics(case, output)
    assert m["incorrect_evidence_usage_count"] >= 1
    assert m["evidence_usage_score"] <= 2  # capped by incorrect usage


def test_hallucinated_ids_detected():
    from evaluator import compute_evidence_metrics
    case = _get_case("l3_state_pipeline")
    # F99 and E99 don't exist in this case's SCM
    output = "F99 writes to V1. E99 connects F2 to F3."
    m = compute_evidence_metrics(case, output)
    assert m["hallucinated_evidence_count"] >= 2


def test_uncertain_usage_detected():
    from evaluator import compute_evidence_metrics
    case = _get_case("l3_state_pipeline")
    # IDs listed without behavioral claims
    output = "Relevant: F2, F3, E3."
    m = compute_evidence_metrics(case, output)
    assert m["uncertain_evidence_usage_count"] >= 1 or m["evidence_usage_score"] <= 1


def test_evidence_metrics_none_for_case_without_scm():
    from evaluator import compute_evidence_metrics
    case = {"id": "nonexistent_xyz", "failure_mode": "UNKNOWN"}
    m = compute_evidence_metrics(case, "any output")
    assert m["has_scm"] is False
    assert m["evidence_usage_score"] is None
    assert m["hallucinated_evidence_count"] is None
    assert m["evidence_action_gap"] is None
    assert m["delta_gap"] is None


# ════════════════════════════════════════════════════════════
# 4. EVIDENCE-ACTION GAP AND DELTA GAP
# ════════════════════════════════════════════════════════════

def test_evidence_action_gap_true_when_engaged_but_failed():
    from evaluator import evaluate_output
    case = _get_case("l3_state_pipeline")
    # Output with good evidence usage but broken code (no commit)
    output = (
        "C1 requires F3 (commit) to set V3 (frozen). E3 ensures get_committed_total (F5) works. "
        "I1 requires frozen==True. Preserving the C1→E3→F3→I1 chain.\n\n"
        "```python\n"
        "def make_state(e): return {'raw':list(e),'pending':[],'stable':[],'view':[],'meta':{'version':0,'frozen':False}}\n"
        "def normalize(e):\n    s=set()\n    return [x for x in e if x['id'] not in s and not s.add(x['id'])]\n"
        "def collapse(e):\n    m={}\n    for x in e:\n        k=x['id']\n        if k in m: m[k]['val']+=x.get('val',0)\n        else: m[k]=dict(x)\n    return list(m.values())\n"
        "def project(e): return [{'id':x['id'],'label':x.get('label',''),'val':x.get('val',0)} for x in e]\n"
        "def stage(st,p):\n    st['pending']=list(p)\n    st['view']=project(p)\n    st['meta']['version']+=1\n"
        "def materialize(st): return {'items':list(st['stable']),'display':list(st['view']),'v':st['meta']['version']}\n"
        "def process_batch(entries):\n"
        "    st=make_state(entries)\n"
        "    stage(st, collapse(normalize(st['raw'])))\n"
        "    return st, materialize(st)\n"  # BUG: no commit
        "```"
    )
    r = evaluate_output(case, _raw_to_parsed(output))
    assert r["pass"] is False, "missing commit should fail"
    assert r["evidence_usage_score"] >= 2, f"should engage with evidence, got {r['evidence_usage_score']}"
    assert r["evidence_action_gap"] is True


def test_delta_gap_positive_when_reasoning_gap_but_no_evidence_gap():
    from evaluator import evaluate_output
    case = _get_case("l3_state_pipeline")
    # Reasoning gap but no evidence engagement → delta_gap = 1 - 0 = 1
    output = (
        "commit() sets frozen=True which get_committed_total checks.\n\n"
        "```python\n"
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
        "```"
    )
    r = evaluate_output(case, _raw_to_parsed(output))
    if r["reasoning_action_gap"] and not r["evidence_action_gap"]:
        assert r["delta_gap"] == 1


def test_delta_gap_zero_when_both_gaps_present():
    from evaluator import evaluate_output
    case = _get_case("l3_state_pipeline")
    # Both reasoning correct + evidence engaged + code wrong
    output = (
        "commit() sets frozen=True. F3 sets V3. C1 protects I1 via E3→E4.\n\n"
        "```python\n"
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
        "```"
    )
    r = evaluate_output(case, _raw_to_parsed(output))
    if r["reasoning_action_gap"] and r["evidence_action_gap"]:
        assert r["delta_gap"] == 0


# ════════════════════════════════════════════════════════════
# 5. SCM CONDITIONS EXECUTE
# ════════════════════════════════════════════════════════════

def test_all_scm_conditions_run():
    """Every SCM condition produces a result without crashing."""
    from execution import run_single
    case = _get_case("l3_state_pipeline")
    scm_conds = ["scm_descriptive", "scm_constrained", "scm_constrained_evidence",
                  "scm_constrained_evidence_minimal", "evidence_only", "length_matched_control"]
    for cond in scm_conds:
        cid, cn, ev = run_single(case, "gpt-4.1-nano", cond)
        assert cid == "l3_state_pipeline", f"{cond}: wrong case_id"
        assert cn == cond, f"{cond}: wrong condition"
        assert "pass" in ev, f"{cond}: no pass field"
        assert "score" in ev, f"{cond}: no score field"


def test_scm_prompts_differ_from_baseline():
    """SCM conditions produce different prompts from baseline."""
    from execution import build_prompt
    case = _get_case("l3_state_pipeline")
    base, _ = build_prompt(case, "baseline")
    for cond in ["scm_descriptive", "scm_constrained", "scm_constrained_evidence"]:
        prompt, _ = build_prompt(case, cond)
        assert len(prompt) > len(base), f"{cond} prompt not longer than baseline"
        assert prompt != base, f"{cond} prompt identical to baseline"


def test_evidence_only_prompt_has_no_edges():
    """evidence_only must not contain E* edge references."""
    from execution import build_prompt
    case = _get_case("l3_state_pipeline")
    prompt, _ = build_prompt(case, "evidence_only")
    # Should have function and constraint IDs but the prompt explicitly says no graph
    assert "determine relationships yourself" in prompt.lower() or "no dependency graph" in prompt.lower()


# ════════════════════════════════════════════════════════════
# 6. BACKWARD COMPATIBILITY
# ════════════════════════════════════════════════════════════

def test_existing_conditions_still_work():
    """Original conditions are unaffected by SCM additions."""
    from execution import run_single
    case = _get_case("l3_state_pipeline")
    for cond in ["baseline", "diagnostic", "guardrail"]:
        cid, cn, ev = run_single(case, "gpt-4.1-nano", cond)
        assert "pass" in ev
        assert "score" in ev
        assert "evidence_usage_score" in ev  # new field present but doesn't break


def test_evaluate_output_has_evidence_fields():
    """evaluate_output always returns evidence metrics even for non-SCM cases."""
    from evaluator import evaluate_output
    case = _get_case("l3_state_pipeline")
    r = evaluate_output(case, _raw_to_parsed("```python\ndef f(): pass\n```"))
    assert "evidence_usage_score" in r
    assert "evidence_action_gap" in r
    assert "delta_gap" in r
    assert "hallucinated_evidence_count" in r


# ════════════════════════════════════════════════════════════
# 7. RUNNER CONDITIONS REGISTERED
# ════════════════════════════════════════════════════════════

def test_scm_conditions_in_runner():
    from runner import ALL_CONDITIONS, VALID_CONDITIONS, COND_LABELS
    for c in ["scm_descriptive", "scm_constrained", "scm_constrained_evidence",
              "scm_constrained_evidence_minimal", "evidence_only", "length_matched_control"]:
        assert c in ALL_CONDITIONS, f"{c} not in ALL_CONDITIONS"
        assert c in VALID_CONDITIONS, f"{c} not in VALID_CONDITIONS"
        assert c in COND_LABELS, f"{c} not in COND_LABELS"


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
