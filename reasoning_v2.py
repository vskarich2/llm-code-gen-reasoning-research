"""V2 reasoning normalization, artifact construction, commitment handling.

Produces the SINGLE canonical NormalizedReasoningArtifactV2 consumed by all
downstream v2 code. No other module may construct this artifact.
"""

import logging
import re
from dataclasses import dataclass, field

from contracts_v2 import CONDITION_TO_SCHEMA
from mapping_v2 import get_canonical_family, is_mapped
from parser_v2 import ParsedGenerationV2

_log = logging.getLogger("t3.reasoning_v2")


@dataclass
class NormalizedReasoningArtifactV2:
    """Canonical normalized v2 reasoning artifact. Consumed by all downstream v2 code."""
    # Identity / provenance
    schema_variant: str
    parse_status: str
    validation_status: str
    validation_errors: list[str] = field(default_factory=list)
    parser_variant: str = "parser_v2"
    output_contract_variant: str = ""
    canonical_family: str | None = None
    canonical_family_mapped: bool = False

    # Raw generation fields (exactly as model produced)
    raw_root_cause: str = ""
    raw_fix_strategy: str = ""
    raw_risk_check: str = ""
    raw_code_commitments: list[str] = field(default_factory=list)

    # Normalized generation fields
    normalized_root_cause: str = ""
    normalized_fix_strategy: str = ""
    normalized_risk_check: str = ""
    normalized_code_commitments: list[str] = field(default_factory=list)
    normalization_notes: list[str] = field(default_factory=list)
    normalization_status: str = ""

    # Commitment provenance
    commitment_count: int = 0
    commitments_source: str = "none"        # "explicit" | "spontaneous" | "none"
    commitment_extractability_status: str = "absent"  # "present" | "absent" | "malformed"

    # File payload
    files_dict: dict | None = None
    full_json: dict | None = None


# ============================================================
# COMMITMENT NORMALIZATION
# ============================================================

def normalize_commitments(raw_commitments: list, notes: list[str] | None = None) -> list[str]:
    """Normalize raw commitment list per the Gold Standard rules.

    Phase A: shape normalization (trim, dedup, list form)
    Phase B: structural normalization (split compounds, scope tagging)
    Phase C: semantic preservation (no invention, no strengthening)

    Returns normalized list. Appends notes to provided list.
    """
    if notes is None:
        notes = []

    # Phase A: shape normalization
    if isinstance(raw_commitments, str):
        raw_commitments = [raw_commitments]
        notes.append("shape: converted string to list")

    if not isinstance(raw_commitments, list):
        notes.append(f"shape: non-list type {type(raw_commitments).__name__}, returning empty")
        return []

    # Trim whitespace, remove empty
    trimmed = [c.strip() for c in raw_commitments if isinstance(c, str) and c.strip()]

    # Remove exact duplicates (case-insensitive), preserve first occurrence order
    seen = set()
    deduped = []
    for c in trimmed:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(c)
        else:
            notes.append(f"dedup: removed duplicate '{c}'")

    # Phase B: structural normalization — split compounds
    result = []
    for c in deduped:
        parts = _try_split_compound(c)
        if len(parts) > 1:
            notes.append(f"split: '{c}' -> {parts}")
        result.extend(parts)

    # Phase B: scope tagging
    final = []
    for c in result:
        if not _has_scope(c):
            tagged = f"[unscoped] {c}"
            notes.append(f"scope: tagged unscoped '{c}'")
            final.append(tagged)
        else:
            final.append(c)

    return final


def _try_split_compound(commitment: str) -> list[str]:
    """Split compound commitment if BOTH halves have scope + verb."""
    # Only split on " and " when both sides have "must" or "should"
    parts = re.split(r'\s+and\s+', commitment, maxsplit=1)
    if len(parts) == 2:
        left, right = parts[0].strip(), parts[1].strip()
        if _has_scope(left) and _has_scope(right):
            return [left, right]
    return [commitment]


def _has_scope(commitment: str) -> bool:
    """Check if a commitment has an identifiable scope (function/variable before must/should)."""
    return bool(re.search(r'\b(must|should)\b', commitment, re.IGNORECASE))


# ============================================================
# NORMALIZATION ENTRY POINT
# ============================================================

def normalize_generation_v2(parsed: ParsedGenerationV2, case: dict, condition: str) -> NormalizedReasoningArtifactV2:
    """Produce the canonical NormalizedReasoningArtifactV2 from parsed generation output.

    This is the ONLY function that creates this artifact. All downstream v2 code
    consumes this artifact only.
    """
    schema_variant = parsed.schema_variant
    contract_variant = f"{schema_variant}_contract"
    canonical = get_canonical_family(case)
    mapped = is_mapped(case)

    # Handle parse failures
    if parsed.full_json is None:
        return NormalizedReasoningArtifactV2(
            schema_variant=schema_variant,
            parse_status=parsed.parse_status,
            validation_status="invalid",
            validation_errors=["no parsed JSON available"],
            output_contract_variant=contract_variant,
            canonical_family=canonical,
            canonical_family_mapped=mapped,
        )

    fj = parsed.full_json

    # Extract raw fields
    raw_root_cause = fj.get("root_cause", "")
    if not isinstance(raw_root_cause, str):
        raw_root_cause = str(raw_root_cause) if raw_root_cause else ""

    raw_fix_strategy = fj.get("fix_strategy", "")
    if not isinstance(raw_fix_strategy, str):
        raw_fix_strategy = str(raw_fix_strategy) if raw_fix_strategy else ""

    raw_risk_check = fj.get("risk_check", "")
    if not isinstance(raw_risk_check, str):
        raw_risk_check = str(raw_risk_check) if raw_risk_check else ""

    raw_code_commitments = fj.get("code_commitments", [])
    if isinstance(raw_code_commitments, str):
        raw_code_commitments = [raw_code_commitments]
    elif not isinstance(raw_code_commitments, list):
        raw_code_commitments = []

    # Determine commitment source
    if schema_variant in ("leg_v2", "lean_v2"):
        if raw_code_commitments:
            commitments_source = "explicit"
            extractability = "present"
        else:
            commitments_source = "none"
            extractability = "absent"
    elif schema_variant == "baseline_v2":
        if "code_commitments" in fj and raw_code_commitments:
            commitments_source = "spontaneous"
            extractability = "present"
        else:
            commitments_source = "none"
            extractability = "absent"
    else:
        commitments_source = "none"
        extractability = "absent"

    # Check for malformed commitments
    orig_raw = fj.get("code_commitments")
    if orig_raw is not None and not isinstance(orig_raw, (list, str)):
        extractability = "malformed"

    # Normalize fields
    normalized_root_cause = raw_root_cause.strip() or "[EMPTY]"
    normalized_fix_strategy = raw_fix_strategy.strip() or "[EMPTY]"
    normalized_risk_check = raw_risk_check.strip()  # "" is valid for baseline_v2

    # Normalize commitments
    norm_notes = []
    normalized_commitments = normalize_commitments(raw_code_commitments, norm_notes)

    norm_status = "clean" if not norm_notes else "normalized"

    return NormalizedReasoningArtifactV2(
        schema_variant=schema_variant,
        parse_status=parsed.parse_status,
        validation_status=parsed.validation_status,
        validation_errors=parsed.validation_errors,
        output_contract_variant=contract_variant,
        canonical_family=canonical,
        canonical_family_mapped=mapped,
        raw_root_cause=raw_root_cause,
        raw_fix_strategy=raw_fix_strategy,
        raw_risk_check=raw_risk_check,
        raw_code_commitments=list(raw_code_commitments),
        normalized_root_cause=normalized_root_cause,
        normalized_fix_strategy=normalized_fix_strategy,
        normalized_risk_check=normalized_risk_check,
        normalized_code_commitments=normalized_commitments,
        normalization_notes=norm_notes,
        normalization_status=norm_status,
        commitment_count=len(normalized_commitments),
        commitments_source=commitments_source,
        commitment_extractability_status=extractability,
        files_dict=parsed.files_dict,
        full_json=parsed.full_json,
    )
