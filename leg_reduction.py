"""LEG (Latent Execution Gap) reduction — minimal adversarial self-check intervention.

Schema (4 fields, all required):
{
    "root_cause": str,
    "fix_strategy": str,
    "risk_check": str,
    "files": {"<path>": "<content or UNCHANGED>"}
}

Parsing uses the SAME recovery pipeline as baseline (parse.parse_model_response)
to ensure parser fairness. The LEG-specific fields (root_cause, fix_strategy,
risk_check) are extracted as reasoning metadata — their absence does NOT block
code extraction.
"""

import json
import logging

_log = logging.getLogger("t3.leg_reduction")

# Required reasoning fields for the LEG intervention.
# Missing fields are recorded as validation warnings, NOT parse failures.
LEG_REQUIRED_FIELDS = ("root_cause", "fix_strategy", "risk_check")


def parse_leg_output(raw: str) -> dict:
    """Parse LEG response using the SAME recovery pathway as baseline.

    Code extraction: delegates to parse.parse_model_response (same lenient
    recovery, same fallback tiers). This ensures parser fairness.

    Reasoning extraction: if the response is valid JSON with root_cause,
    fix_strategy, risk_check fields, these are extracted as structured
    reasoning. If any are missing, it is a validation warning — NOT a
    parse error and NOT a code extraction failure.

    Returns dict compatible with the existing evaluate_case pipeline:
        code: str
        reasoning: str (root_cause + fix_strategy + risk_check concatenated)
        files: dict | None
        parse_error: str | None
        response_format: str
        leg_fields: dict (root_cause, fix_strategy, risk_check — or empty)
        leg_valid: bool (all 3 fields present and non-empty)
        leg_warnings: list[str]
    """
    from parse import parse_model_response

    # Use the EXACT same parser as baseline — same tiers, same recovery
    base_parsed = parse_model_response(raw)

    # Extract LEG-specific reasoning fields from raw JSON (if parseable)
    leg_fields = {}
    leg_warnings = []
    raw_json = None

    try:
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped.rsplit("```", 1)[0]
        raw_json = json.loads(stripped.strip())
    except (json.JSONDecodeError, TypeError, IndexError):
        raw_json = None

    if isinstance(raw_json, dict):
        for field in LEG_REQUIRED_FIELDS:
            value = raw_json.get(field)
            if isinstance(value, str) and value.strip():
                leg_fields[field] = value.strip()
            else:
                leg_warnings.append(f"missing or empty: {field}")
    else:
        leg_warnings.append("response is not a JSON object — LEG fields unavailable")

    leg_valid = len(leg_fields) == len(LEG_REQUIRED_FIELDS)

    # Build structured reasoning from LEG fields
    reasoning_parts = []
    if "root_cause" in leg_fields:
        reasoning_parts.append(f"Root cause: {leg_fields['root_cause']}")
    if "fix_strategy" in leg_fields:
        reasoning_parts.append(f"Fix strategy: {leg_fields['fix_strategy']}")
    if "risk_check" in leg_fields:
        reasoning_parts.append(f"Risk check: {leg_fields['risk_check']}")
    leg_reasoning = "\n\n".join(reasoning_parts)

    reasoning = leg_reasoning if leg_reasoning else (base_parsed.get("reasoning") or "")

    result = dict(base_parsed)
    result["reasoning"] = reasoning
    result["leg_fields"] = leg_fields
    result["leg_valid"] = leg_valid
    result["leg_warnings"] = leg_warnings
    result["_raw_json"] = raw_json

    if leg_warnings:
        _log.info("LEG validation warnings: %s", leg_warnings)

    return result
