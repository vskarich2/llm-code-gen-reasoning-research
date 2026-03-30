"""V2 canonical bug-family mapping.

Single authoritative mapping from case failure_mode to canonical commitment family.
The canonical families match the section headers in classify_reasoning_v2.j2.
"""

FAILURE_MODE_TO_CANONICAL = {
    "ALIASING": "ALIASING",
    "PARTIAL_STATE_UPDATE": "PARTIAL_STATE_UPDATE",
    "STALE_CACHE": "STALE_CACHE",
    "MUTABLE_DEFAULT": "MUTABLE_DEFAULT",
    "SIDE_EFFECT_ORDER": "SIDE_EFFECT_ORDER",
    "USE_BEFORE_SET": "USE_BEFORE_SET",
    "RETRY_DUPLICATION": "RETRY_DUPLICATION",
    "PARTIAL_ROLLBACK": "PARTIAL_ROLLBACK",
    "TEMPORAL_DRIFT": "TEMPORAL_DRIFT",
    "MISSING_BRANCH": "MISSING_BRANCH",
}

UNMAPPED_FAILURE_MODES = frozenset({
    "EARLY_RETURN", "WRONG_CONDITION", "INIT_ORDER", "SILENT_DEFAULT",
    "INDEX_MISALIGN", "HIDDEN_DEPENDENCY", "INVARIANT_VIOLATION",
    "STATE_SEMANTIC_VIOLATION", "RACE_CONDITION", "TEMPORAL_ORDERING",
    "FLAG_DRIFT", "CACHE_ORDERING",
})

ALL_CANONICAL_FAMILIES = frozenset(FAILURE_MODE_TO_CANONICAL.values())


def get_canonical_family(case: dict) -> str | None:
    """Return canonical commitment family for a case, or None if unmapped."""
    return FAILURE_MODE_TO_CANONICAL.get(case.get("failure_mode"))


def is_mapped(case: dict) -> bool:
    """Check if case has a canonical commitment family."""
    return get_canonical_family(case) is not None
