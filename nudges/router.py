"""Nudge router — selects and applies the right operator for a case.

HARDENED: No silent degradation. Missing nudge mappings raise RuntimeError.
Identity transforms (prompt unchanged after condition) raise RuntimeError.
"""

import nudges.core  # noqa: F401 — triggers operator registration

from nudges.mapping import get_operators_for_case
from nudges.operators import get
from nudges.core import build_strict_guardrail


def _require_assignment(case_id: str, condition: str):
    """Get operator assignment or raise. Never returns None."""
    assignment = get_operators_for_case(case_id)
    if assignment is None:
        raise RuntimeError(
            f"CONDITION INTEGRITY FAILURE: condition '{condition}' requires nudge mapping "
            f"for case '{case_id}', but no entry exists in CASE_TO_OPERATORS. "
            f"This (case, condition) pair should have been blocked by pre-flight validation."
        )
    return assignment


def _assert_modified(result: str, base_prompt: str, case_id: str, condition: str, op_name: str):
    """Assert the condition actually modified the prompt."""
    if result == base_prompt:
        raise RuntimeError(
            f"IDENTITY TRANSFORM: {condition} operator '{op_name}' returned unchanged "
            f"prompt for case '{case_id}'. Condition had no effect — this is a no-op bug."
        )


def apply_diagnostic(case_id: str, base_prompt: str) -> str:
    assignment = _require_assignment(case_id, "diagnostic")
    result = get(assignment.diagnostic).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "diagnostic", assignment.diagnostic)
    return result


def apply_guardrail(case_id: str, base_prompt: str) -> str:
    assignment = _require_assignment(case_id, "guardrail")
    result = get(assignment.guardrail).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "guardrail", assignment.guardrail)
    return result


def apply_guardrail_strict(case_id: str, base_prompt: str, hard_constraints: list[str]) -> str:
    assignment = _require_assignment(case_id, "guardrail_strict")
    soft = get(assignment.guardrail).build_prompt(base_prompt)
    result = build_strict_guardrail(soft, hard_constraints)
    _assert_modified(result, base_prompt, case_id, "guardrail_strict", assignment.guardrail)
    return result


def apply_counterfactual(case_id: str, base_prompt: str) -> str:
    assignment = get_operators_for_case(case_id)
    op_name = assignment.counterfactual if assignment else "COUNTERFACTUAL"
    result = get(op_name).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "counterfactual", op_name)
    return result


def apply_reason_then_act(case_id: str, base_prompt: str) -> str:
    assignment = get_operators_for_case(case_id)
    op_name = assignment.reason_then_act if assignment else "REASON_THEN_ACT"
    result = get(op_name).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "reason_then_act", op_name)
    return result


def apply_self_check(case_id: str, base_prompt: str) -> str:
    assignment = get_operators_for_case(case_id)
    op_name = assignment.self_check if assignment else "SELF_CHECK"
    result = get(op_name).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "self_check", op_name)
    return result


def apply_counterfactual_check(case_id: str, base_prompt: str) -> str:
    assignment = get_operators_for_case(case_id)
    op_name = assignment.counterfactual_check if assignment else "COUNTERFACTUAL_CHECK"
    result = get(op_name).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "counterfactual_check", op_name)
    return result


def apply_test_driven(case_id: str, base_prompt: str) -> str:
    assignment = get_operators_for_case(case_id)
    op_name = assignment.test_driven if assignment else "TEST_DRIVEN"
    result = get(op_name).build_prompt(base_prompt)
    _assert_modified(result, base_prompt, case_id, "test_driven", op_name)
    return result


def get_operator_names(case_id: str) -> dict[str, str | None]:
    assignment = get_operators_for_case(case_id)
    if not assignment:
        return {"diagnostic": None, "guardrail": None,
                "counterfactual": "COUNTERFACTUAL", "reason_then_act": "REASON_THEN_ACT",
                "self_check": "SELF_CHECK", "counterfactual_check": "COUNTERFACTUAL_CHECK",
                "test_driven": "TEST_DRIVEN"}
    return {
        "diagnostic": assignment.diagnostic,
        "guardrail": assignment.guardrail,
        "counterfactual": assignment.counterfactual,
        "reason_then_act": assignment.reason_then_act,
        "self_check": assignment.self_check,
        "counterfactual_check": assignment.counterfactual_check,
        "test_driven": assignment.test_driven,
    }
