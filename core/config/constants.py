"""Shared constants for T3 benchmark.

This module is the SOLE source of truth for condition names, labels, and categories.
Imported by: config.py, runner.py, execution_v2.py.
Must NOT import from any of those modules (no circular deps).

V2.1: Legacy v1 conditions REMOVED. Only v2 conditions are valid.
"""

# V2 conditions ONLY. Legacy conditions have been removed.
V2_CONDITIONS = frozenset({
    "baseline_v2",
    "leg_reduction_v2",
    "leg_reduction_lean_v2",
    "retry_no_contract_v2",
    "retry_adaptive_v2",
    "retry_leg_critique_v2",
    "retry_leg_critique_strict_v2",
    "retry_leg_critique_moderate_v2",
    "retry_leg_critique_aggressive_v2",
    "retry_bare_retry_v2",
    "retry_reasoning_only_critique_v1",
    # V3 prompt family
    "baseline_v3",
    "leg_reduction_lean_v3",
})

ALL_CONDITIONS = list(sorted(V2_CONDITIONS))
VALID_CONDITIONS = V2_CONDITIONS

# Legacy categories — empty. No legacy conditions exist.
RETRY_CONDITIONS = frozenset()
MULTISTEP_CONDITIONS = frozenset()
SIMPLE_CONDITIONS = VALID_CONDITIONS

COND_LABELS = {
    "baseline_v2": "B2",
    "leg_reduction_v2": "L2",
    "leg_reduction_lean_v2": "LL",
    "retry_no_contract_v2": "RV",
    "retry_adaptive_v2": "AV",
    "retry_leg_critique_v2": "LX",
    "retry_leg_critique_strict_v2": "LS",
    "retry_leg_critique_moderate_v2": "LM",
    "retry_leg_critique_aggressive_v2": "LA",
    "retry_bare_retry_v2": "BX",
    "retry_reasoning_only_critique_v1": "RO",
    # V3 prompt family
    "baseline_v3": "B3",
    "leg_reduction_lean_v3": "L3",
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
