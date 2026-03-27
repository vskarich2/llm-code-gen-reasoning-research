"""Shared constants for T3 benchmark.

This module is the SOLE source of truth for condition names, labels, and categories.
Imported by: config.py, runner.py, execution.py, templates.py.
Must NOT import from any of those modules (no circular deps).
"""

ALL_CONDITIONS = [
    "baseline",
    "diagnostic",
    "guardrail",
    "guardrail_strict",
    "counterfactual",
    "reason_then_act",
    "self_check",
    "counterfactual_check",
    "test_driven",
    "repair_loop",
    # SCM experiment conditions
    "scm_descriptive",
    "scm_constrained",
    "scm_constrained_evidence",
    "scm_constrained_evidence_minimal",
    "evidence_only",
    "length_matched_control",
    # Reasoning interface conditions
    "structured_reasoning",
    "free_form_reasoning",
    "branching_reasoning",
    # Contract-Gated Execution
    "contract_gated",
    # Retry harness (trajectory probe)
    "retry_no_contract",
    "retry_with_contract",
    "retry_adaptive",
    "retry_alignment",
    # LEG-reduction (intra-call self-correction)
    "leg_reduction",
]

VALID_CONDITIONS = frozenset(ALL_CONDITIONS)

# -- Condition categories (structural invariants for config validation) --
#
# These define which template keys are REQUIRED and FORBIDDEN per condition.

# Conditions that use a retry loop with retry_template.
# MUST have retry_template. MUST NOT have next_template.
RETRY_CONDITIONS = frozenset(
    {
        "retry_no_contract",
        "retry_with_contract",
        "retry_adaptive",
        "retry_alignment",
        "repair_loop",
    }
)

# Multi-step conditions. MUST have BOTH next_template and retry_template.
MULTISTEP_CONDITIONS = frozenset(
    {
        "contract_gated",
    }
)

# All other conditions. MUST have ONLY template. MUST NOT have retry_template or next_template.
SIMPLE_CONDITIONS = VALID_CONDITIONS - RETRY_CONDITIONS - MULTISTEP_CONDITIONS

# INVARIANT: categories must be exhaustive and non-overlapping
assert RETRY_CONDITIONS | MULTISTEP_CONDITIONS | SIMPLE_CONDITIONS == VALID_CONDITIONS
assert not (RETRY_CONDITIONS & MULTISTEP_CONDITIONS)
assert not (RETRY_CONDITIONS & SIMPLE_CONDITIONS)
assert not (MULTISTEP_CONDITIONS & SIMPLE_CONDITIONS)

COND_LABELS = {
    "baseline": "BL",
    "diagnostic": "DX",
    "guardrail": "GR",
    "guardrail_strict": "GS",
    "counterfactual": "CF",
    "reason_then_act": "RA",
    "self_check": "SC",
    "counterfactual_check": "CC",
    "test_driven": "TD",
    "repair_loop": "RL",
    "scm_descriptive": "SD",
    "scm_constrained": "SK",
    "scm_constrained_evidence": "SE",
    "scm_constrained_evidence_minimal": "SM",
    "evidence_only": "EO",
    "length_matched_control": "LC",
    "structured_reasoning": "SR",
    "free_form_reasoning": "FF",
    "branching_reasoning": "BR",
    "contract_gated": "CG",
    "retry_no_contract": "RN",
    "retry_with_contract": "RC",
    "retry_adaptive": "AD",
    "retry_alignment": "AL",
    "leg_reduction": "LR",
}

# INVARIANT: condition labels must be unique
assert len(set(COND_LABELS.values())) == len(
    COND_LABELS
), "FATAL: Duplicate condition labels detected."

# INVARIANT: every condition must have a label
assert (
    set(COND_LABELS.keys()) == VALID_CONDITIONS
), "FATAL: COND_LABELS keys do not match VALID_CONDITIONS."

# Current config schema version
CURRENT_CONFIG_VERSION = 1
