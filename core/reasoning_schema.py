"""Reasoning schema constants and pure extraction functions.

No evaluation logic. No classification. Just schema definitions
and dict extraction used by both parsing and evaluation layers.
"""

REASONING_SCHEMA_VERSION = 3

# Baseline reasoning schema (4 fields)
BASELINE_REASONING_FIELDS = ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy")

# Minimal LEG reasoning schema (3 fields — root_cause + fix_strategy shared with baseline)
LEG_REASONING_FIELDS = ("root_cause", "fix_strategy", "risk_check")

# Reasoning is "present" if EITHER the baseline set OR the LEG set is satisfied.
REQUIRED_REASONING_FIELDS = BASELINE_REASONING_FIELDS  # backward compat alias
MIN_FIELD_LENGTH = 10

# Valid failure types — shared across v1 and v2 evaluation
VALID_FAILURE_TYPES = frozenset({
    "HIDDEN_DEPENDENCY", "TEMPORAL_ORDERING", "INVARIANT_VIOLATION",
    "PARTIAL_STATE_UPDATE", "RETRY_LOGIC_BUG", "EDGE_CASE_MISSED",
    "LOGGING_INCONSISTENCY", "CONFOUNDING_LOGIC", "UNKNOWN",
})


def extract_reasoning_obj(parsed_json):
    """Extract structured reasoning from parsed JSON. No fallback. No legacy.

    Extracts fields from BOTH baseline and LEG schemas — whatever is present.
    """
    obj = {}
    # Baseline fields
    for field in BASELINE_REASONING_FIELDS:
        obj[field] = parsed_json.get(field, "")
    # LEG field (risk_check — the adversarial self-check)
    obj["risk_check"] = parsed_json.get("risk_check", "")
    # Legacy LEG fields (may be present in old case_data)
    obj["alternative_hypothesis"] = parsed_json.get("alternative_hypothesis", "")
    obj["hypothesis_rejection"] = parsed_json.get("hypothesis_rejection", "")
    raw_sc = parsed_json.get("self_check", "")
    if isinstance(raw_sc, dict):
        obj["self_check"] = raw_sc
    else:
        obj["self_check"] = raw_sc if isinstance(raw_sc, str) else ""
    return obj


def validate_reasoning(reasoning_obj, raw_json):
    """Check presence and length. No semantic validation — that's the classifier's job."""
    # Check both schemas
    baseline_attempted = all(field in raw_json for field in BASELINE_REASONING_FIELDS)
    leg_attempted = all(field in raw_json for field in LEG_REASONING_FIELDS)
    attempted = baseline_attempted or leg_attempted

    # Compute lengths for all fields present in either schema
    all_fields = set(BASELINE_REASONING_FIELDS) | set(LEG_REASONING_FIELDS)
    lengths = {}
    for f in all_fields:
        val = reasoning_obj.get(f, "")
        if isinstance(val, str):
            val = val.strip()
        else:
            val = str(val).strip() if val else ""
        lengths[f] = {"length": len(val), "present": bool(val and len(val) >= MIN_FIELD_LENGTH)}

    # Present if ALL fields of EITHER schema are present
    baseline_present = all(
        lengths.get(f, {}).get("present", False) for f in BASELINE_REASONING_FIELDS
    )
    leg_present = all(
        lengths.get(f, {}).get("present", False) for f in LEG_REASONING_FIELDS
    )
    present = baseline_present or leg_present

    # Determine which schema was matched
    schema_matched = "baseline" if baseline_present else ("leg" if leg_present else "none")

    return {
        "attempted": attempted,
        "present": present,
        "schema_matched": schema_matched,
        "lengths": lengths,
    }
