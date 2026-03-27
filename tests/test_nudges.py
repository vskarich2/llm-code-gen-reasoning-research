"""Tests for the nudge operator framework."""

import sys
from pathlib import Path

# Add parent to path so imports work when running from tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nudges.operators import get, list_operators, list_by_kind
from nudges.mapping import get_operators_for_case, CASE_TO_OPERATORS
from nudges.router import apply_diagnostic, apply_guardrail, get_operator_names

# Import core to trigger registration
import nudges.core  # noqa: F401

# ── Operator registration ────────────────────────────────────


def test_core_operators_registered():
    ops = list_operators()
    assert "DEPENDENCY_CHECK" in ops
    assert "INVARIANT_GUARD" in ops
    assert "TEMPORAL_ROBUSTNESS" in ops
    assert "STATE_LIFECYCLE" in ops


def test_guardrail_operators_registered():
    ops = list_operators()
    assert "DEPENDENCY_CHECK_GUARDRAIL" in ops
    assert "INVARIANT_GUARD_GUARDRAIL" in ops
    assert "TEMPORAL_ROBUSTNESS_GUARDRAIL" in ops
    assert "STATE_LIFECYCLE_GUARDRAIL" in ops


def test_list_by_kind():
    diagnostics = list_by_kind("diagnostic")
    guardrails = list_by_kind("guardrail")
    assert len(diagnostics) >= 4
    assert len(guardrails) >= 4
    assert all("GUARDRAIL" not in d for d in diagnostics)
    assert all("GUARDRAIL" in g for g in guardrails)


def test_get_operator():
    op = get("DEPENDENCY_CHECK")
    assert op.name == "DEPENDENCY_CHECK"
    assert op.kind == "diagnostic"
    assert callable(op.build_prompt)


def test_get_unknown_raises():
    try:
        get("NONEXISTENT_OPERATOR")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass


# ── Mapping ──────────────────────────────────────────────────


def test_mapping_returns_correct_operators():
    assignment = get_operators_for_case("hidden_dep_multihop")
    assert assignment is not None
    assert assignment.diagnostic == "DEPENDENCY_CHECK"
    assert assignment.guardrail == "DEPENDENCY_CHECK_GUARDRAIL"


def test_mapping_returns_none_for_unknown():
    assert get_operators_for_case("nonexistent_case") is None


def test_all_mapped_cases_have_valid_operators():
    for case_id, assignment in CASE_TO_OPERATORS.items():
        # Should not raise
        get(assignment.diagnostic)
        get(assignment.guardrail)


# ── Router ───────────────────────────────────────────────────


def test_router_modifies_prompt():
    base = "Refactor this code."
    nudged = apply_diagnostic("hidden_dep_multihop", base)
    assert nudged != base
    assert base in nudged
    assert len(nudged) > len(base)


def test_router_guardrail_modifies_prompt():
    base = "Simplify this pipeline."
    nudged = apply_guardrail("invariant_partial_fail", base)
    assert nudged != base
    assert "MANDATORY CONSTRAINTS" in nudged


def test_router_raises_for_unknown_case():
    """Router must CRASH on unmapped case — never silently return base prompt."""
    base = "Do something."
    try:
        apply_diagnostic("unknown_case_id", base)
        assert False, "Should have raised RuntimeError for unknown case"
    except RuntimeError as e:
        assert "CONDITION INTEGRITY FAILURE" in str(e)
    try:
        apply_guardrail("unknown_case_id", base)
        assert False, "Should have raised RuntimeError for unknown case"
    except RuntimeError as e:
        assert "CONDITION INTEGRITY FAILURE" in str(e)


def test_router_diagnostic_and_guardrail_differ():
    base = "Refactor."
    dx = apply_diagnostic("l3_state_pipeline", base)
    gr = apply_guardrail("l3_state_pipeline", base)
    assert dx != gr
    assert "MANDATORY CONSTRAINTS" in gr
    assert "MANDATORY CONSTRAINTS" not in dx


def test_get_operator_names():
    names = get_operator_names("hidden_dep_multihop")
    assert names["diagnostic"] == "DEPENDENCY_CHECK"
    assert names["guardrail"] == "DEPENDENCY_CHECK_GUARDRAIL"


def test_get_operator_names_unknown():
    names = get_operator_names("nonexistent")
    assert names["diagnostic"] is None
    assert names["guardrail"] is None


# ── Run all tests ────────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
