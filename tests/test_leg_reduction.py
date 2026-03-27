"""Tests for LEG-Reduction Pipeline with auditable revision trace.

Validates:
  1. Schema compliance — all required fields in revision_history entries
  2. Causal consistency — issues→changes, no fake iterations, no no-ops
  3. Revision ordering — sequential indices, count consistency
  4. Invariant tracking — required, PASS/FAIL with evidence
  5. Code binding — code_before/code_after, changed_functions
  6. Backward compatibility — top-level fields derived correctly
  7. Integration — full pipeline mock flow
  8. Rejection — invalid inputs caught explicitly
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

from leg_reduction import (
    build_leg_reduction_prompt,
    parse_leg_reduction_output,
    MAX_INTERNAL_REVISIONS,
)

# ============================================================
# HELPERS — build valid objects
# ============================================================


def _make_valid_single_revision():
    """A valid output with 1 revision (model got it right first try)."""
    v = [
        {
            "step": "Add rollback in except",
            "status": "PASS",
            "evidence": "except block has balance += amount",
        },
    ]
    return {
        "bug_diagnosis": "Missing rollback after debit",
        "plan_steps": [
            {"step": "Add rollback in except", "intended_effect": "restore balance on failure"}
        ],
        "revision_history": [
            {
                "revision": 0,
                "verification": v,
                "invariants_checked": [
                    {
                        "invariant": "balance conserved",
                        "status": "PASS",
                        "evidence": "except restores sender.balance",
                    },
                ],
                "issues_found": [],
                "changes_made": None,
                "changed_functions": [],
                "code_before": "def f(): pass",
                "code_after": "def f(): return 1",
            }
        ],
        "verification": v,
        "code": "def f(): return 1",
        "internal_revisions": 0,
    }


def _make_valid_two_revisions():
    """A valid output with 2 revisions (model self-corrected once)."""
    v0 = [
        {"step": "Add rollback", "status": "FAIL", "evidence": "no except block found"},
    ]
    v1 = [
        {"step": "Add rollback", "status": "PASS", "evidence": "except block restores balance"},
    ]
    return {
        "bug_diagnosis": "Missing rollback",
        "plan_steps": [{"step": "Add rollback", "intended_effect": "restore balance"}],
        "revision_history": [
            {
                "revision": 0,
                "verification": v0,
                "invariants_checked": [
                    {
                        "invariant": "balance conserved",
                        "status": "FAIL",
                        "evidence": "no rollback path",
                    },
                ],
                "issues_found": [
                    {
                        "issue_id": "ISS-1",
                        "description": "no except block",
                        "evidence": "line 5 missing try",
                        "related_invariant": "balance conserved",
                    },
                ],
                "changes_made": None,
                "changed_functions": [],
                "code_before": "def f(): pass",
                "code_after": "def f(): pass",  # first attempt still broken
            },
            {
                "revision": 1,
                "verification": v1,
                "invariants_checked": [
                    {
                        "invariant": "balance conserved",
                        "status": "PASS",
                        "evidence": "except block present",
                    },
                ],
                "issues_found": [],
                "changes_made": [
                    {
                        "change_type": "add",
                        "target": "execute_transfer",
                        "description": "added try/except with rollback",
                    },
                ],
                "changed_functions": ["execute_transfer"],
                "code_before": "def f(): pass",
                "code_after": "def f(): return 1",
            },
        ],
        "verification": v1,
        "code": "def f(): return 1",
        "internal_revisions": 1,
    }


# ============================================================
# 1. SCHEMA COMPLIANCE
# ============================================================


def test_valid_single_revision_parses():
    raw = json.dumps(_make_valid_single_revision())
    r = parse_leg_reduction_output(raw)
    assert r["valid"] is True, f"errors: {r.get('validation_errors')}"
    assert r["parse_error"] is None
    assert r["internal_revisions"] == 0
    assert r["all_steps_verified"] is True
    assert len(r["revision_history"]) == 1


def test_valid_two_revisions_parses():
    raw = json.dumps(_make_valid_two_revisions())
    r = parse_leg_reduction_output(raw)
    assert r["valid"] is True, f"errors: {r.get('validation_errors')}"
    assert r["internal_revisions"] == 1
    assert len(r["revision_history"]) == 2


def test_missing_revision_history_fails():
    d = _make_valid_single_revision()
    del d["revision_history"]
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "revision_history" in r["parse_error"]


def test_empty_revision_history_fails():
    d = _make_valid_single_revision()
    d["revision_history"] = []
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "non-empty" in r["parse_error"]


def test_revision_missing_required_field_fails():
    d = _make_valid_single_revision()
    del d["revision_history"][0]["invariants_checked"]
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "invariants_checked" in r["parse_error"]


def test_verification_entry_requires_evidence():
    d = _make_valid_single_revision()
    # Remove evidence from both revision_history and top-level verification
    d["revision_history"][0]["verification"][0] = {
        "step": "Add rollback in except",
        "status": "PASS",
        # evidence deliberately omitted
    }
    d["verification"][0] = {"step": "Add rollback in except", "status": "PASS"}
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "evidence" in r["parse_error"]


def test_verification_status_must_be_pass_or_fail():
    d = _make_valid_single_revision()
    d["revision_history"][0]["verification"][0]["status"] = "true"
    d["verification"][0]["status"] = "true"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "PASS or FAIL" in r["parse_error"]


def test_invariant_status_must_be_pass_or_fail():
    d = _make_valid_single_revision()
    d["revision_history"][0]["invariants_checked"][0]["status"] = "ok"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "PASS or FAIL" in r["parse_error"]


def test_change_type_must_be_add_modify_delete():
    d = _make_valid_two_revisions()
    d["revision_history"][1]["changes_made"][0]["change_type"] = "rewrite"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "add/modify/delete" in r["parse_error"]


# ============================================================
# 2. CAUSAL CONSISTENCY
# ============================================================


def test_no_op_revision_detected():
    """code_before == code_after with no changes → invalid."""
    d = _make_valid_two_revisions()
    # Make revision 1 a no-op
    d["revision_history"][1]["code_before"] = "same"
    d["revision_history"][1]["code_after"] = "same"
    d["revision_history"][1]["changes_made"] = []
    d["code"] = "same"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert "no-op" in str(r.get("validation_errors", []))


def test_fake_iteration_detected():
    """Changes without prior issues → invalid."""
    d = _make_valid_two_revisions()
    # Remove all failures from revision 0
    d["revision_history"][0]["verification"][0]["status"] = "PASS"
    d["revision_history"][0]["invariants_checked"][0]["status"] = "PASS"
    d["revision_history"][0]["issues_found"] = []
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("revision 0 has no failures" in e for e in r.get("validation_errors", []))


def test_revision_0_must_have_null_changes():
    d = _make_valid_single_revision()
    d["revision_history"][0]["changes_made"] = [
        {"change_type": "add", "target": "f", "description": "added"}
    ]
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("null for revision 0" in e for e in r.get("validation_errors", []))


def test_revision_0_must_have_empty_changed_functions():
    d = _make_valid_single_revision()
    d["revision_history"][0]["changed_functions"] = ["f"]
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("[] for revision 0" in e for e in r.get("validation_errors", []))


# ============================================================
# 3. REVISION ORDERING
# ============================================================


def test_revision_index_must_match_position():
    d = _make_valid_two_revisions()
    d["revision_history"][1]["revision"] = 5  # wrong index
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("revision=5 but expected 1" in e for e in r.get("validation_errors", []))


def test_internal_revisions_must_match_history_length():
    d = _make_valid_two_revisions()
    d["internal_revisions"] = 0  # should be 1
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("internal_revisions=0" in e for e in r.get("validation_errors", []))


# ============================================================
# 4. TOP-LEVEL CONSISTENCY
# ============================================================


def test_top_level_verification_must_match_last_revision():
    d = _make_valid_single_revision()
    d["verification"] = [{"step": "WRONG STEP", "status": "PASS", "evidence": "wrong"}]
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("mismatch" in e for e in r.get("validation_errors", []))


def test_top_level_code_must_match_last_code_after():
    d = _make_valid_single_revision()
    d["code"] = "TOTALLY DIFFERENT CODE"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is False
    assert any("code_after" in e for e in r.get("validation_errors", []))


# ============================================================
# 5. ALL STEPS VERIFIED LOGIC
# ============================================================


def test_all_pass_means_verified():
    r = parse_leg_reduction_output(json.dumps(_make_valid_single_revision()))
    assert r["all_steps_verified"] is True


def test_any_fail_means_not_verified():
    d = _make_valid_single_revision()
    d["revision_history"][0]["verification"][0]["status"] = "FAIL"
    d["verification"][0]["status"] = "FAIL"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["valid"] is True  # schema valid, just has failures
    assert r["all_steps_verified"] is False


def test_exceeded_max_revisions_flagged():
    d = _make_valid_single_revision()
    d["internal_revisions"] = MAX_INTERNAL_REVISIONS + 1
    # Need matching revision_history length
    d["revision_history"] = [d["revision_history"][0]]
    for i in range(1, MAX_INTERNAL_REVISIONS + 2):
        entry = {
            "revision": i,
            "verification": d["verification"],
            "invariants_checked": d["revision_history"][0]["invariants_checked"],
            "issues_found": (
                []
                if i == MAX_INTERNAL_REVISIONS + 1
                else [
                    {
                        "issue_id": f"ISS-{i}",
                        "description": "still broken",
                        "evidence": "...",
                        "related_invariant": None,
                    }
                ]
            ),
            "changes_made": [{"change_type": "modify", "target": "f", "description": "attempt"}],
            "changed_functions": ["f"],
            "code_before": f"v{i-1}",
            "code_after": f"v{i}",
        }
        d["revision_history"].append(entry)
    d["code"] = f"v{MAX_INTERNAL_REVISIONS + 1}"
    r = parse_leg_reduction_output(json.dumps(d))
    assert r["leg_reduction_exceeded_max_revisions"] is True


# ============================================================
# 6. JSON / PARSE EDGE CASES
# ============================================================


def test_empty_input_fails():
    r = parse_leg_reduction_output("")
    assert r["valid"] is False
    assert "empty" in r["parse_error"].lower()


def test_non_json_fails():
    r = parse_leg_reduction_output("plain text, no JSON")
    assert r["valid"] is False


def test_truncated_json_fails():
    r = parse_leg_reduction_output('{"bug_diagnosis": "x"')
    assert r["valid"] is False


def test_markdown_fences_stripped():
    d = _make_valid_single_revision()
    raw = f"```json\n{json.dumps(d)}\n```"
    r = parse_leg_reduction_output(raw)
    assert r["valid"] is True


def test_trailing_text_ok():
    d = _make_valid_single_revision()
    raw = f"{json.dumps(d)}\n\nExtra explanation here."
    r = parse_leg_reduction_output(raw)
    assert r["valid"] is True


# ============================================================
# 7. BACKWARD COMPATIBILITY + INTEGRATION
# ============================================================


def test_prompt_contains_revision_history_schema():
    prompt = build_leg_reduction_prompt("Fix bug.", {"main.py": "x = 1"})
    assert "revision_history" in prompt
    assert "invariants_checked" in prompt
    assert "issues_found" in prompt
    assert "changes_made" in prompt
    assert "code_before" in prompt
    assert "code_after" in prompt
    assert "changed_functions" in prompt
    assert "SELF-CORRECT" in prompt
    assert str(MAX_INTERNAL_REVISIONS) in prompt


def test_leg_reduction_condition_registered():
    from runner import ALL_CONDITIONS, COND_LABELS, VALID_CONDITIONS

    assert "leg_reduction" in ALL_CONDITIONS
    assert "leg_reduction" in COND_LABELS
    assert "leg_reduction" in VALID_CONDITIONS


def test_leg_reduction_full_flow_mock():
    from execution import run_leg_reduction
    from runner import load_cases

    case = load_cases(case_id="l3_state_pipeline")[0]
    cid, cond, ev = run_leg_reduction(case, "gpt-4.1-nano")
    assert cid == "l3_state_pipeline"
    assert cond == "leg_reduction"
    assert "pass" in ev
    assert "score" in ev
    lr = ev["leg_reduction"]
    assert (
        lr["valid_schema"] is True
    ), f"Schema invalid: {lr['parse_error']}, errors: {lr.get('validation_errors')}"
    assert "revision_history" in lr
    assert len(lr["revision_history"]) >= 1
    assert "revision_count" in lr
    assert lr["revision_count"] >= 1


def test_leg_reduction_mock_has_invariants():
    from execution import run_leg_reduction
    from runner import load_cases

    case = load_cases(case_id="l3_state_pipeline")[0]
    _, _, ev = run_leg_reduction(case, "gpt-4.1-nano")
    lr = ev["leg_reduction"]
    rev0 = lr["revision_history"][0]
    assert len(rev0["invariants_checked"]) > 0
    for inv in rev0["invariants_checked"]:
        assert "invariant" in inv
        assert "status" in inv
        assert "evidence" in inv
        assert inv["status"] in ("PASS", "FAIL")


def test_leg_reduction_result_has_standard_eval_fields():
    from execution import run_leg_reduction
    from runner import load_cases

    case = load_cases(case_id="l3_state_pipeline")[0]
    _, _, ev = run_leg_reduction(case, "gpt-4.1-nano")
    for field in [
        "pass",
        "score",
        "reasons",
        "failure_modes",
        "execution",
        "operator_used",
        "condition",
        "alignment",
    ]:
        assert field in ev, f"Missing standard eval field: {field}"


def test_existing_baseline_still_works():
    from execution import run_single
    from runner import load_cases

    case = load_cases(case_id="l3_state_pipeline")[0]
    cid, cond, ev = run_single(case, "gpt-4.1-nano", "baseline")
    assert cid == "l3_state_pipeline"
    assert "pass" in ev
