"""Core nudge operator registration.

ALL instruction text has been moved to prompts/registry.yaml.
These registrations exist ONLY for name lookup by the nudge mapping system.
No prompt text exists in this file.
"""

from nudges.operators import NudgeOperator, register


def _stub(base: str) -> str:
    """Stub — operator text is in registry.yaml, not here."""
    raise RuntimeError("Nudge operators are resolved via prompt_registry, not build_prompt().")


# Diagnostic operators (text in registry.yaml under diagnostic__generic_*)
register(NudgeOperator(name="DEPENDENCY_CHECK", kind="diagnostic",
    description="Traces downstream consumers and side-effect dependencies.", build_prompt=_stub))
register(NudgeOperator(name="INVARIANT_GUARD", kind="diagnostic",
    description="Reasons about invariants, failure windows, and atomicity.", build_prompt=_stub))
register(NudgeOperator(name="TEMPORAL_ROBUSTNESS", kind="diagnostic",
    description="Traces data flow and ordering constraints.", build_prompt=_stub))
register(NudgeOperator(name="STATE_LIFECYCLE", kind="diagnostic",
    description="Traces state transitions and selector dependencies.", build_prompt=_stub))

# Guardrail operators (text in registry.yaml under guardrail__generic_*)
register(NudgeOperator(name="DEPENDENCY_CHECK_GUARDRAIL", kind="guardrail",
    description="Constrains removal of shared-state write operations.", build_prompt=_stub))
register(NudgeOperator(name="INVARIANT_GUARD_GUARDRAIL", kind="guardrail",
    description="Constrains separation of paired debit/credit operations.", build_prompt=_stub))
register(NudgeOperator(name="TEMPORAL_ROBUSTNESS_GUARDRAIL", kind="guardrail",
    description="Constrains merging pre/post-transform computations.", build_prompt=_stub))
register(NudgeOperator(name="STATE_LIFECYCLE_GUARDRAIL", kind="guardrail",
    description="Constrains removal of state transition steps.", build_prompt=_stub))

# Reasoning operators (text in registry.yaml under reasoning__*)
register(NudgeOperator(name="COUNTERFACTUAL", kind="counterfactual",
    description="Counterfactual state transition check.", build_prompt=_stub))
register(NudgeOperator(name="REASON_THEN_ACT", kind="reason_then_act",
    description="Two-step forced reasoning before code.", build_prompt=_stub))
register(NudgeOperator(name="SELF_CHECK", kind="self_check",
    description="Post-solution verification step.", build_prompt=_stub))
register(NudgeOperator(name="COUNTERFACTUAL_CHECK", kind="counterfactual_check",
    description="Counterfactual failure analysis.", build_prompt=_stub))
register(NudgeOperator(name="TEST_DRIVEN", kind="test_driven",
    description="Behavioral requirements check.", build_prompt=_stub))
