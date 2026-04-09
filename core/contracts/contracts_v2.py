"""V2 generation and classifier schema contracts.

Single source of truth for required fields per v2 condition.
No v2 parsing, normalization, or evaluation logic belongs here.
"""

from dataclasses import dataclass, field

# ============================================================
# GENERATION SCHEMA CONTRACTS
# ============================================================

V2_BASELINE_REQUIRED = frozenset({"root_cause", "fix_strategy", "files"})
V2_BASELINE_OPTIONAL = frozenset({"code_commitments"})  # accepted but not required
V2_LEG_REQUIRED = frozenset({"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"})
V2_LEAN_REQUIRED = frozenset({"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"})

SCHEMA_REQUIRED_FIELDS = {
    "baseline_v2": V2_BASELINE_REQUIRED,
    "leg_v2": V2_LEG_REQUIRED,
    "lean_v2": V2_LEAN_REQUIRED,
}

# Conditions that map to each schema variant
V3_BASELINE_REQUIRED = frozenset({"root_cause", "fix_strategy", "code_commitments", "files"})
V3_LEAN_REQUIRED = frozenset({"root_cause", "fix_strategy", "code_commitments", "files"})

CONDITION_TO_SCHEMA = {
    "baseline_v2": "baseline_v2",
    "leg_reduction_v2": "leg_v2",
    "leg_reduction_lean_v2": "lean_v2",
    "baseline_v3": "baseline_v3",
    "leg_reduction_lean_v3": "lean_v3",
}

SCHEMA_REQUIRED_FIELDS["baseline_v3"] = V3_BASELINE_REQUIRED
SCHEMA_REQUIRED_FIELDS["lean_v3"] = V3_LEAN_REQUIRED

V2_CONDITIONS = frozenset(CONDITION_TO_SCHEMA.keys())

# ============================================================
# CLASSIFIER V2 CONTRACT
# ============================================================

V2_CLASSIFIER_DIMENSIONS = (
    "reasoning_internal_consistency",
    "commitments_extracted",
    "commitments_satisfied",
    "reasoning_code_alignment",
)

V2_VALID_DIMENSION_VALUES = frozenset({"CORRECT", "PARTIAL", "WRONG"})
V3_VALID_DIMENSION_VALUES = frozenset({"CORRECT", "INCORRECT"})
V2_VALID_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})

# ============================================================
# VALIDATION HELPERS
# ============================================================

MIN_FIELD_LENGTH = 10


def validate_generation_fields(full_json: dict, schema_variant: str) -> tuple[str, list[str]]:
    """Validate required fields for a v2 generation schema.

    Returns (status, errors) where status is "valid", "partial", or "invalid".
    """
    required = SCHEMA_REQUIRED_FIELDS.get(schema_variant)
    if required is None:
        return "invalid", [f"unknown schema_variant: {schema_variant}"]

    errors = []
    for f in required:
        if f not in full_json:
            errors.append(f"missing required field: {f}")
        elif f == "files":
            if not isinstance(full_json[f], dict) or len(full_json[f]) == 0:
                errors.append(f"files must be a non-empty dict")
        elif f == "code_commitments":
            val = full_json[f]
            if not isinstance(val, (list, str)):
                errors.append(f"code_commitments must be list or string, got {type(val).__name__}")
            elif isinstance(val, list) and len(val) == 0:
                errors.append("code_commitments is empty list")
        elif f in ("root_cause", "fix_strategy"):
            val = full_json[f]
            if not isinstance(val, str) or len(val.strip()) < MIN_FIELD_LENGTH:
                errors.append(f"{f} must be a string with length >= {MIN_FIELD_LENGTH}")
        elif f == "risk_check":
            val = full_json[f]
            if not isinstance(val, str) or not val.strip():
                errors.append("risk_check must be a non-empty string")
            # "SAFE" is valid for lean_v2
        # files validation above covers the files case

    # Validate optional fields when present (e.g. code_commitments in baseline)
    if "code_commitments" in full_json and "code_commitments" not in required:
        val = full_json["code_commitments"]
        if not isinstance(val, (list, str)):
            errors.append(f"code_commitments must be list or string, got {type(val).__name__}")
        elif isinstance(val, list) and len(val) == 0:
            errors.append("code_commitments is empty list")

    if not errors:
        return "valid", []
    elif any("missing required" in e for e in errors):
        return "invalid", errors
    else:
        return "partial", errors
