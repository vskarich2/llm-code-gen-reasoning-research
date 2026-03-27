"""Condition Compatibility Registry.

Central authority for which (case, condition) pairs are valid.
No condition runs without passing this check. No silent degradation.

Usage:
    from condition_registry import validate_run, get_safe_conditions

    # Before a run:
    validate_run(cases, conditions)  # raises if incompatible

    # Get conditions safe for a set of cases:
    safe = get_safe_conditions(cases)
"""

import logging
from dataclasses import dataclass, field

_log = logging.getLogger("t3.registry")


# ============================================================
# CONDITION REQUIREMENTS
# ============================================================


@dataclass(frozen=True)
class ConditionSpec:
    """Declares what a condition needs to run."""

    name: str
    requires_nudge_mapping: bool = False  # needs entry in CASE_TO_OPERATORS
    requires_scm_data: bool = False  # needs entry in scm_data
    requires_hard_constraints: bool = False  # needs case["hard_constraints"] non-empty
    requires_case_specific_data: bool = False  # any case-specific asset
    universal: bool = False  # safe for ALL cases without any lookup
    description: str = ""


# Every condition must be registered here. No exceptions.
CONDITION_SPECS: dict[str, ConditionSpec] = {
    # === UNIVERSAL — safe for all cases ===
    "baseline": ConditionSpec(
        name="baseline", universal=True, description="Terse prompt, no augmentation"
    ),
    "structured_reasoning": ConditionSpec(
        name="structured_reasoning",
        universal=True,
        description="Generic structured reasoning template",
    ),
    "free_form_reasoning": ConditionSpec(
        name="free_form_reasoning",
        universal=True,
        description="Generic free-form reasoning template",
    ),
    "branching_reasoning": ConditionSpec(
        name="branching_reasoning",
        universal=True,
        description="Generic branching reasoning (ToT-lite)",
    ),
    "contract_gated": ConditionSpec(
        name="contract_gated",
        universal=True,
        description="CGE: elicit contract → generate → gate → retry",
    ),
    "retry_no_contract": ConditionSpec(
        name="retry_no_contract",
        universal=True,
        description="Retry loop with test feedback, no contract",
    ),
    "retry_with_contract": ConditionSpec(
        name="retry_with_contract",
        universal=True,
        description="Retry loop with contract context on retry",
    ),
    "retry_adaptive": ConditionSpec(
        name="retry_adaptive",
        universal=True,
        description="Retry with failure-classifier-guided hints",
    ),
    "retry_alignment": ConditionSpec(
        name="retry_alignment",
        universal=True,
        description="Retry with plan-code alignment measurement",
    ),
    "leg_reduction": ConditionSpec(
        name="leg_reduction",
        universal=True,
        description="Intra-call self-correction: plan → code → verify → revise",
    ),
    # === RESTRICTED — need per-case nudge mappings ===
    "diagnostic": ConditionSpec(
        name="diagnostic",
        requires_nudge_mapping=True,
        description="Case-specific diagnostic reasoning scaffold",
    ),
    "guardrail": ConditionSpec(
        name="guardrail",
        requires_nudge_mapping=True,
        description="Case-specific action constraints",
    ),
    "guardrail_strict": ConditionSpec(
        name="guardrail_strict",
        requires_nudge_mapping=True,
        requires_hard_constraints=True,
        description="Guardrail + hard constraints",
    ),
    "repair_loop": ConditionSpec(
        name="repair_loop",
        requires_nudge_mapping=True,
        description="2-attempt repair with diagnostic on attempt 1",
    ),
    # === RESTRICTED — need per-case operator mappings ===
    "counterfactual": ConditionSpec(
        name="counterfactual",
        requires_case_specific_data=True,
        description="Counterfactual simulation prompt",
    ),
    "reason_then_act": ConditionSpec(
        name="reason_then_act",
        requires_case_specific_data=True,
        description="Reason-then-act scaffold",
    ),
    "self_check": ConditionSpec(
        name="self_check",
        requires_case_specific_data=True,
        description="Post-generation self-check",
    ),
    "counterfactual_check": ConditionSpec(
        name="counterfactual_check",
        requires_case_specific_data=True,
        description="Counterfactual failure check",
    ),
    "test_driven": ConditionSpec(
        name="test_driven",
        requires_case_specific_data=True,
        description="Test-driven invariant prompting",
    ),
    # === RESTRICTED — need SCM data ===
    "scm_descriptive": ConditionSpec(
        name="scm_descriptive", requires_scm_data=True, description="SCM descriptive causal graph"
    ),
    "scm_constrained": ConditionSpec(
        name="scm_constrained", requires_scm_data=True, description="SCM with constraints"
    ),
    "scm_constrained_evidence": ConditionSpec(
        name="scm_constrained_evidence",
        requires_scm_data=True,
        description="SCM with evidence annotations",
    ),
    "scm_constrained_evidence_minimal": ConditionSpec(
        name="scm_constrained_evidence_minimal",
        requires_scm_data=True,
        description="SCM evidence (minimal)",
    ),
    "evidence_only": ConditionSpec(
        name="evidence_only", requires_scm_data=True, description="Evidence IDs only, no graph"
    ),
    "length_matched_control": ConditionSpec(
        name="length_matched_control",
        requires_scm_data=True,
        description="Length-matched filler (control for SCM)",
    ),
}


# ============================================================
# COMPATIBILITY CHECK
# ============================================================


def check_compatibility(case: dict, condition: str) -> tuple[bool, str]:
    """Check if a (case, condition) pair is valid.

    Returns (compatible, reason).
    If compatible=False, reason explains why.
    """
    spec = CONDITION_SPECS.get(condition)
    if spec is None:
        return False, f"Unknown condition '{condition}' — not in registry"

    if spec.universal:
        return True, "universal condition"

    case_id = case.get("id", "?")

    if spec.requires_nudge_mapping:
        from nudges.mapping import get_operators_for_case

        assignment = get_operators_for_case(case_id)
        if assignment is None:
            return False, (
                f"condition '{condition}' requires nudge mapping but "
                f"case '{case_id}' has no entry in CASE_TO_OPERATORS"
            )
        # For diagnostic/guardrail, check the specific operator exists
        if condition == "diagnostic" and not assignment.diagnostic:
            return False, f"case '{case_id}' has mapping but diagnostic operator is empty"
        if condition in ("guardrail", "guardrail_strict") and not assignment.guardrail:
            return False, f"case '{case_id}' has mapping but guardrail operator is empty"

    if spec.requires_hard_constraints:
        constraints = case.get("hard_constraints", [])
        if not constraints:
            return False, (
                f"condition '{condition}' requires hard_constraints but "
                f"case '{case_id}' has empty or missing hard_constraints"
            )

    if spec.requires_scm_data:
        from scm_data import get_scm

        scm = get_scm(case_id)
        if scm is None:
            return False, (
                f"condition '{condition}' requires SCM data but "
                f"case '{case_id}' has no entry in scm_data"
            )

    if spec.requires_case_specific_data:
        # These conditions use generic operators as fallback —
        # but we still need to verify the operator exists
        from nudges.operators import get as get_operator

        fallback_map = {
            "counterfactual": "COUNTERFACTUAL",
            "reason_then_act": "REASON_THEN_ACT",
            "self_check": "SELF_CHECK",
            "counterfactual_check": "COUNTERFACTUAL_CHECK",
            "test_driven": "TEST_DRIVEN",
        }
        op_name = fallback_map.get(condition)
        if op_name:
            try:
                op = get_operator(op_name)
                if op is None:
                    return False, f"generic operator '{op_name}' not registered"
            except Exception as e:
                return False, f"generic operator '{op_name}' lookup failed: {e}"

    return True, "all requirements met"


def validate_run(cases: list[dict], conditions: list[str]) -> None:
    """Validate ALL (case, condition) pairs before an experiment.

    Raises RuntimeError with full details if ANY pair is incompatible.
    """
    errors = []
    for case in cases:
        for cond in conditions:
            ok, reason = check_compatibility(case, cond)
            if not ok:
                errors.append(
                    f"  INCOMPATIBLE: condition={cond}, case={case.get('id','?')}: {reason}"
                )

    if errors:
        msg = (
            f"PRE-FLIGHT FAILED — {len(errors)} incompatible (case, condition) pairs:\n"
            + "\n".join(errors)
            + "\n\nAblation BLOCKED. Fix compatibility or remove incompatible conditions."
        )
        _log.error(msg)
        raise RuntimeError(msg)

    _log.info(
        "Pre-flight passed: %d cases × %d conditions = %d valid pairs",
        len(cases),
        len(conditions),
        len(cases) * len(conditions),
    )


def get_safe_conditions(cases: list[dict] | None = None) -> list[str]:
    """Return conditions that are safe for ALL given cases (or all universal if no cases)."""
    if cases is None:
        return [name for name, spec in CONDITION_SPECS.items() if spec.universal]

    safe = []
    for name, spec in CONDITION_SPECS.items():
        all_ok = all(check_compatibility(case, name)[0] for case in cases)
        if all_ok:
            safe.append(name)
    return safe


def get_condition_sets() -> dict[str, list[str]]:
    """Return named condition sets for experiment configuration."""
    return {
        "universal": [n for n, s in CONDITION_SPECS.items() if s.universal],
        "restricted_nudge": [n for n, s in CONDITION_SPECS.items() if s.requires_nudge_mapping],
        "restricted_scm": [n for n, s in CONDITION_SPECS.items() if s.requires_scm_data],
        "all": list(CONDITION_SPECS.keys()),
    }
