"""Failure-type to operator mapping.

Maps each benchmark case to its operator set.
To add a new case, add one entry here — no other file changes needed.
"""

from dataclasses import dataclass


@dataclass
class NudgeAssignment:
    diagnostic: str
    guardrail: str
    counterfactual: str = "COUNTERFACTUAL"
    reason_then_act: str = "REASON_THEN_ACT"
    self_check: str = "SELF_CHECK"
    counterfactual_check: str = "COUNTERFACTUAL_CHECK"
    test_driven: str = "TEST_DRIVEN"


# Case ID -> operator assignment
# All cases use generic counterfactual/reason_then_act/self_check
CASE_TO_OPERATORS: dict[str, NudgeAssignment] = {
    "hidden_dep_multihop": NudgeAssignment(
        diagnostic="DEPENDENCY_CHECK",
        guardrail="DEPENDENCY_CHECK_GUARDRAIL",
    ),
    "temporal_semantic_drift": NudgeAssignment(
        diagnostic="TEMPORAL_ROBUSTNESS",
        guardrail="TEMPORAL_ROBUSTNESS_GUARDRAIL",
    ),
    "invariant_partial_fail": NudgeAssignment(
        diagnostic="INVARIANT_GUARD",
        guardrail="INVARIANT_GUARD_GUARDRAIL",
    ),
    "l3_state_pipeline": NudgeAssignment(
        diagnostic="STATE_LIFECYCLE",
        guardrail="STATE_LIFECYCLE_GUARDRAIL",
    ),
    # New cases use generic diagnostic/guardrail operators
    "async_race_lock": NudgeAssignment(
        diagnostic="DEPENDENCY_CHECK",
        guardrail="DEPENDENCY_CHECK_GUARDRAIL",
    ),
    "idempotency_trap": NudgeAssignment(
        diagnostic="INVARIANT_GUARD",
        guardrail="INVARIANT_GUARD_GUARDRAIL",
    ),
    "cache_invalidation_order": NudgeAssignment(
        diagnostic="DEPENDENCY_CHECK",
        guardrail="DEPENDENCY_CHECK_GUARDRAIL",
    ),
    "partial_rollback_multi": NudgeAssignment(
        diagnostic="INVARIANT_GUARD",
        guardrail="INVARIANT_GUARD_GUARDRAIL",
    ),
    "lazy_init_hazard": NudgeAssignment(
        diagnostic="STATE_LIFECYCLE",
        guardrail="STATE_LIFECYCLE_GUARDRAIL",
    ),
    "external_timing_dep": NudgeAssignment(
        diagnostic="TEMPORAL_ROBUSTNESS",
        guardrail="TEMPORAL_ROBUSTNESS_GUARDRAIL",
    ),
    "shared_ref_coupling": NudgeAssignment(
        diagnostic="DEPENDENCY_CHECK",
        guardrail="DEPENDENCY_CHECK_GUARDRAIL",
    ),
    "log_side_effect_order": NudgeAssignment(
        diagnostic="TEMPORAL_ROBUSTNESS",
        guardrail="TEMPORAL_ROBUSTNESS_GUARDRAIL",
    ),
    "retry_causality": NudgeAssignment(
        diagnostic="INVARIANT_GUARD",
        guardrail="INVARIANT_GUARD_GUARDRAIL",
    ),
    "feature_flag_drift": NudgeAssignment(
        diagnostic="DEPENDENCY_CHECK",
        guardrail="DEPENDENCY_CHECK_GUARDRAIL",
    ),
}


def get_operators_for_case(case_id: str) -> NudgeAssignment | None:
    return CASE_TO_OPERATORS.get(case_id)
