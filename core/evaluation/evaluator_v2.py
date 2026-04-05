"""V2 classifier invocation, output parsing, and result assembly.

This module owns:
- Building classifier v2 prompt variables
- Invoking the classifier LLM
- Parsing classifier v2 output (dedicated parser, not v1)
- Assembling the final v2 result dict
"""

import json
import logging
import re
from dataclasses import dataclass, field, asdict

from core.contracts.contracts_v2 import (
    V2_CLASSIFIER_DIMENSIONS, V2_VALID_DIMENSION_VALUES, V2_VALID_CONFIDENCE,
)

_log = logging.getLogger("t3.evaluator_v2")


# Debug section delimiter — everything at and after this is ignored
_DEBUG_DELIMITER = "---DEBUG---"


@dataclass
class ClassifierResultV2:
    """Parsed classifier output (v2 and v3 schemas)."""
    # V2 dimensions (populated by v2 parser, None when v3 parser used)
    mechanism_identified: str | None = None
    commitments_extracted: str | None = None
    commitments_satisfied: str | None = None

    # Shared dimension (same name in v2 and v3)
    reasoning_code_alignment: str | None = None

    # V3 dimensions (populated by v3 parser, None when v2 parser used)
    reasoning_internal_consistency: str | None = None
    commitments_internal_consistency: str | None = None
    commitments_code_consistency: str | None = None

    # V3 justifications (debug only — MUST NOT affect metrics)
    reasoning_internal_consistency_justification: str = ""
    commitments_internal_consistency_justification: str = ""
    commitments_code_consistency_justification: str = ""
    reasoning_code_alignment_justification: str = ""

    # Metadata
    failure_type: str = "UNKNOWN"
    failure_type_raw: str = ""
    confidence: str = ""
    counterfactual: str = ""
    evidence: str = ""
    judgment: str = ""
    parse_error: str | None = None
    classify_raw: str = ""
    classifier_schema_variant: str = "v2_5line"
    classifier_prompt_variant: str = "classify_reasoning_v2"
    commitment_source_for_classifier: str = ""
    failure_type_parse_warning: str | None = None


def _extract_canonical_dims(result: ClassifierResultV2) -> dict:
    """THE ONLY SOURCE OF TRUTH FOR DIMENSION MAPPING.

    Maps v3 or v2 classifier fields to canonical signal names.
    No other code may read dimension fields directly from the result.

    Returns dict with keys: mechanism_identified, commitments_extracted,
    commitments_satisfied, reasoning_code_alignment.
    """
    v3_fields = (
        result.reasoning_internal_consistency,
        result.commitments_internal_consistency,
        result.commitments_code_consistency,
    )
    v2_fields = (
        result.mechanism_identified,
        result.commitments_extracted,
        result.commitments_satisfied,
    )

    v3_populated = any(f is not None for f in v3_fields)
    v2_populated = any(f is not None for f in v2_fields)

    if v3_populated and v2_populated:
        raise RuntimeError(
            "Mixed classifier state: both v2 and v3 dimension fields "
            "are populated. This indicates a parser bug."
        )

    if v3_populated:
        if not all(f is not None for f in v3_fields):
            raise RuntimeError(
                "Partial v3 classifier state: some v3 fields are None. "
                f"ric={result.reasoning_internal_consistency}, "
                f"cic={result.commitments_internal_consistency}, "
                f"ccc={result.commitments_code_consistency}"
            )
        return {
            "mechanism_identified": result.reasoning_internal_consistency,
            "commitments_extracted": result.commitments_internal_consistency,
            "commitments_satisfied": result.commitments_code_consistency,
            "reasoning_code_alignment": result.reasoning_code_alignment,
        }

    return {
        "mechanism_identified": result.mechanism_identified,
        "commitments_extracted": result.commitments_extracted,
        "commitments_satisfied": result.commitments_satisfied,
        "reasoning_code_alignment": result.reasoning_code_alignment,
    }


# ============================================================
# CLASSIFIER V2 PROMPT BUILDER
# ============================================================



def build_classifier_v2_vars(artifact, case: dict, code: str, config) -> dict:
    """Build template variables for classify_reasoning_v2.j2.

    artifact: NormalizedReasoningArtifactV2
    """
    eval_cfg = config.models.evaluator

    def _field_or_missing(val):
        if isinstance(val, str) and val.strip() and val != "[EMPTY]":
            return val.strip()
        return None  # FIX-NOW-2: return None, not placeholder

    # Determine what commitment source the classifier should see
    if artifact.commitments_source == "explicit":
        source_for_classifier = "explicit"
    elif artifact.commitments_source == "spontaneous":
        source_for_classifier = "spontaneous"
    else:
        source_for_classifier = "none"

    # Canonical family
    canonical = artifact.canonical_family or "[UNMAPPED]"

    root_cause = _field_or_missing(artifact.normalized_root_cause)
    fix_strategy = _field_or_missing(artifact.normalized_fix_strategy)
    risk_check = _field_or_missing(artifact.normalized_risk_check)

    # FIX-NOW-2: if core reasoning fields are missing, signal skip
    # Do NOT send fabricated "[COULD NOT EXTRACT]" to the classifier
    if root_cause is None and fix_strategy is None:
        return None, "skip:missing_reasoning_fields"

    # Pass code_commitments if available
    commitments_str = ""
    if artifact.normalized_code_commitments:
        commitments_str = "; ".join(artifact.normalized_code_commitments)

    from core.pipeline.checks import check_classifier_code_nonempty
    check_classifier_code_nonempty(code, case.get("id", "?"))

    variables = {
        "root_cause": root_cause or "",
        "fix_strategy": fix_strategy or "",
        "risk_check": risk_check or "",
        "code_commitments": commitments_str,
        "task": case.get("task", ""),
        "code": (code or ""),
        "classifier_mode": config.evaluation.classifier_mode,
    }

    # Grounded mode fields
    if config.evaluation.classifier_mode == "grounded":
        variables["ground_truth_failure_mode"] = case.get("failure_mode", "")
        variables["ground_truth_trap"] = case.get("trap", "")
        gt_bug = case.get("ground_truth_bug", {})
        variables["ground_truth_invariant"] = gt_bug.get("invariant", "") if isinstance(gt_bug, dict) else ""

    return variables, source_for_classifier


# ============================================================
# CANONICAL CLASSIFIER ENTRYPOINT
# ============================================================

def classify_case(artifact, case: dict, code: str, config, logger,
                  parent_event_id, condition: str, cid: str) -> tuple:
    """Canonical classifier. Called by execution_v2 and retry_v2.

    Owns: variable assembly, prompt compilation, model call, output parsing.
    No other module may build classifier prompts or parse classifier outputs.

    Returns (ClassifierResultV2, classify_event_id).
    """
    from core.pipeline.llm import call_model

    classifier_result = ClassifierResultV2()
    classify_eid = parent_event_id

    build_result = build_classifier_v2_vars(artifact, case, code, config)

    if build_result is None or build_result[0] is None:
        skip_reason = build_result[1] if build_result else "unknown"
        classifier_result.parse_error = f"classifier_skipped:{skip_reason}"
        return classifier_result, classify_eid

    classifier_vars, source_for_classifier = build_result
    classifier_result.commitment_source_for_classifier = source_for_classifier

    # Compile classifier prompt
    from core.pipeline.orchestration.execution_v2 import _compile_prompt_from_components
    classify_prompt = _compile_prompt_from_components(
        (config.evaluation.classifier_template,), classifier_vars
    ).final_prompt

    # Call evaluator model
    classify_gen = call_model(
        classify_prompt,
        model=config.models.evaluator.name,
        raw=True,
        logger=logger, case_id=cid, phase="classification",
        condition=condition,
        parent_event_id=parent_event_id,
    )
    assert classify_gen.event_id is not None, \
        "call_model must return event_id in classifier path"
    classify_eid = classify_gen.event_id

    # Parse classifier output — select parser by schema variant
    if config.evaluation.classifier_schema_variant == "v3_json":
        classifier_result = parse_classifier_v3_output(classify_gen.response)
    else:
        classifier_result = parse_classifier_v2_output(classify_gen.response)
    classifier_result.commitment_source_for_classifier = source_for_classifier

    return classifier_result, classify_eid


# ============================================================
# CLASSIFIER V2 OUTPUT PARSER
# ============================================================

def _strip_debug(raw: str) -> str:
    """Strip optional ---DEBUG--- section."""
    idx = raw.find(_DEBUG_DELIMITER)
    if idx != -1:
        return raw[:idx]
    return raw


def parse_classifier_v2_output(raw: str) -> ClassifierResultV2:
    """Parse v2 classifier output. Dedicated parser — does NOT use v1 parser.

    Expected structure (Evidence/Judgment may span multiple lines):
      Line 1: <mechanism>;<commitments_extracted>;<commitments_satisfied>;<alignment>
      Line 2: <confidence>
      Counterfactual: <sentence>
      Evidence: <bullets — may span multiple lines>
      Judgment: <sentence — may span multiple lines>
    """
    result = ClassifierResultV2(classify_raw=raw)

    if not raw or not raw.strip():
        result.parse_error = "empty classifier response"
        return result

    stripped = _strip_debug(raw)
    lines = [l.strip() for l in stripped.strip().split("\n") if l.strip()]

    if len(lines) < 5:
        result.parse_error = f"expected at least 5 lines, got {len(lines)}"
        return result

    # Line 1: 4 or 5 semicolon-separated fields (4 dimensions, optional legacy failure_type)
    parts = [p.strip().upper() for p in lines[0].split(";")]
    if len(parts) < 4:
        result.parse_error = f"line 1: expected at least 4 fields, got {len(parts)}"
        return result

    dims = {}
    for name, val in zip(V2_CLASSIFIER_DIMENSIONS, parts[:4]):
        if val not in V2_VALID_DIMENSION_VALUES:
            result.parse_error = f"invalid dimension {name}={val}"
            return result
        dims[name] = val

    result.mechanism_identified = dims["mechanism_identified"]
    result.commitments_extracted = dims["commitments_extracted"]
    result.commitments_satisfied = dims["commitments_satisfied"]
    result.reasoning_code_alignment = dims["reasoning_code_alignment"]

    # Legacy failure_type (5th field, optional — tolerated but not required)
    if len(parts) >= 5:
        result.failure_type_raw = parts[4]

    # Line 2: confidence
    confidence = lines[1].strip().upper()
    if confidence not in V2_VALID_CONFIDENCE:
        result.parse_error = f"invalid confidence: {confidence}"
        return result
    result.confidence = confidence

    # Lines 3+: Collect Counterfactual, Evidence, Judgment sections
    # These may span multiple lines (especially Evidence with bullet points)
    remaining = lines[2:]
    sections = {"counterfactual": [], "evidence": [], "judgment": []}
    current_section = None
    _prefixes = {
        "counterfactual:": "counterfactual",
        "evidence:": "evidence",
        "judgment:": "judgment",
    }

    # FIX-NOW-4: capture preamble lines (before first section prefix)
    preamble_lines = []
    for line in remaining:
        lower = line.lower()
        matched = False
        for prefix, section_name in _prefixes.items():
            if lower.startswith(prefix):
                current_section = section_name
                content = line[len(prefix):].strip()
                if content:
                    sections[section_name].append(content)
                matched = True
                break
        if not matched:
            if current_section:
                sections[current_section].append(line)
            else:
                preamble_lines.append(line)

    # Attach preamble to counterfactual if it exists
    if preamble_lines and sections["counterfactual"]:
        sections["counterfactual"] = preamble_lines + sections["counterfactual"]
    elif preamble_lines and not sections["counterfactual"]:
        sections["counterfactual"] = preamble_lines

    result.counterfactual = " ".join(sections["counterfactual"]).strip()
    result.evidence = " ".join(sections["evidence"]).strip()
    result.judgment = " ".join(sections["judgment"]).strip()

    if not result.counterfactual:
        result.parse_error = "missing counterfactual"
        return result
    if not result.evidence:
        result.parse_error = "missing evidence"
        return result
    if not result.judgment:
        result.parse_error = "missing judgment"
        return result

    result.parse_error = None
    return result


# ============================================================
# V3 CLASSIFIER PARSER (8-field JSON: 4 dimensions + 4 justifications)
# ============================================================

_V3_DIMENSION_KEYS = frozenset({
    "reasoning_internal_consistency",
    "commitments_internal_consistency",
    "commitments_code_consistency",
    "reasoning_code_alignment",
})
_V3_JUSTIFICATION_KEYS = frozenset({
    "reasoning_internal_consistency_justification",
    "commitments_internal_consistency_justification",
    "commitments_code_consistency_justification",
    "reasoning_code_alignment_justification",
})
_V3_EXPECTED_KEYS = _V3_DIMENSION_KEYS | _V3_JUSTIFICATION_KEYS
_V3_VALID_DIMS = frozenset({"CORRECT", "INCORRECT"})


def parse_classifier_v3_output(raw: str) -> ClassifierResultV2:
    """Parse v3 classifier JSON output.

    Strict 8-field schema:
    - 4 dimension fields ∈ {CORRECT, INCORRECT}
    - 4 justification fields (non-empty strings, ≥10 chars)
    - No extra keys allowed
    """
    result = ClassifierResultV2(
        classify_raw=raw,
        classifier_schema_variant="v3_json",
        classifier_prompt_variant="classify_reasoning_v3",
    )

    if not raw or not raw.strip():
        result.parse_error = "empty classifier response"
        return result

    stripped = _strip_debug(raw).strip()

    if not stripped.startswith("{"):
        result.parse_error = "non_json_prefix: response does not start with '{'"
        return result

    last_brace = stripped.rfind("}")
    if last_brace == -1:
        result.parse_error = "no_closing_brace"
        return result
    trailing = stripped[last_brace + 1:].strip()
    if trailing:
        result.parse_error = f"trailing_text_after_json: {trailing[:50]!r}"
        return result

    try:
        d = json.loads(stripped)
    except json.JSONDecodeError as e:
        result.parse_error = f"json_decode_error: {e}"
        return result

    # Strict schema: exact key set, no extras
    if set(d.keys()) != _V3_EXPECTED_KEYS:
        extra = set(d.keys()) - _V3_EXPECTED_KEYS
        missing = _V3_EXPECTED_KEYS - set(d.keys())
        result.parse_error = f"schema_mismatch: extra={extra}, missing={missing}"
        return result

    # Validate dimension values
    for key in _V3_DIMENSION_KEYS:
        val = d[key]
        if not isinstance(val, str) or val not in _V3_VALID_DIMS:
            result.parse_error = f"invalid_dimension: {key}={val!r}"
            return result

    # Validate justifications
    for key in _V3_JUSTIFICATION_KEYS:
        val = d[key]
        if not isinstance(val, str) or len(val.strip()) < 10:
            result.parse_error = (
                f"justification_too_short: {key} ({len(str(val).strip())} chars)"
            )
            return result

    justifications = [d[k].strip() for k in sorted(_V3_JUSTIFICATION_KEYS)]
    if len(set(justifications)) == 1:
        result.parse_error = "all_justifications_identical"
        return result

    # Populate V3 dimensions
    result.reasoning_internal_consistency = d["reasoning_internal_consistency"]
    result.commitments_internal_consistency = d["commitments_internal_consistency"]
    result.commitments_code_consistency = d["commitments_code_consistency"]
    result.reasoning_code_alignment = d["reasoning_code_alignment"]

    # Populate justifications
    result.reasoning_internal_consistency_justification = d["reasoning_internal_consistency_justification"]
    result.commitments_internal_consistency_justification = d["commitments_internal_consistency_justification"]
    result.commitments_code_consistency_justification = d["commitments_code_consistency_justification"]
    result.reasoning_code_alignment_justification = d["reasoning_code_alignment_justification"]

    result.parse_error = None
    return result


# ============================================================
# RESULT ASSEMBLY
# ============================================================

def assemble_v2_result(
    exec_result: dict,
    artifact,       # NormalizedReasoningArtifactV2
    classifier: ClassifierResultV2,
    signals,        # V2Signals
    case: dict,
    condition: str,
    model: str,
) -> dict:
    """Assemble the final ev dict for a v2 evaluation.

    This dict is what gets logged. It contains ALL v2 fields.
    """
    ev = dict(exec_result)  # start with execution results (pass, score, reasons, etc.)

    # V2 identity
    ev["condition"] = condition
    ev["schema_variant"] = artifact.schema_variant
    ev["operator_used"] = condition.upper()

    # V2 artifact (full normalized reasoning)
    ev["v2_artifact"] = {
        "raw_root_cause": artifact.raw_root_cause,
        "raw_fix_strategy": artifact.raw_fix_strategy,
        "raw_risk_check": artifact.raw_risk_check,
        "raw_code_commitments": artifact.raw_code_commitments,
        "normalized_root_cause": artifact.normalized_root_cause,
        "normalized_fix_strategy": artifact.normalized_fix_strategy,
        "normalized_risk_check": artifact.normalized_risk_check,
        "normalized_code_commitments": artifact.normalized_code_commitments,
        "normalization_notes": artifact.normalization_notes,
        "normalization_status": artifact.normalization_status,
        "commitment_count": artifact.commitment_count,
        "commitments_source": artifact.commitments_source,
        "commitment_extractability_status": artifact.commitment_extractability_status,
        "canonical_family": artifact.canonical_family,
        "canonical_family_mapped": artifact.canonical_family_mapped,
        "validation_status": artifact.validation_status,
        "validation_errors": artifact.validation_errors,
        "parse_status": artifact.parse_status,
    }

    # V2 primary signals
    ev["mechanism_correct"] = signals.mechanism_correct
    ev["commitments_valid"] = signals.commitments_valid
    ev["alignment_positive"] = signals.alignment_positive
    ev["commitments_satisfied_positive"] = signals.commitments_satisfied_positive

    # V2 classifier dimensions (raw)
    canonical = _extract_canonical_dims(classifier)
    ev["mechanism_identified_dim"] = canonical["mechanism_identified"]
    ev["commitments_extracted_dim"] = canonical["commitments_extracted"]
    ev["commitments_satisfied_dim"] = canonical["commitments_satisfied"]
    ev["reasoning_code_alignment_dim"] = canonical["reasoning_code_alignment"]

    # V2 classifier metadata
    ev["classify_v2_raw"] = classifier.classify_raw
    ev["classify_v2_parse_error"] = classifier.parse_error
    ev["failure_type"] = classifier.failure_type_raw or "UNKNOWN"
    ev["confidence"] = classifier.confidence
    ev["counterfactual"] = classifier.counterfactual
    ev["evidence"] = classifier.evidence
    ev["judgment"] = classifier.judgment
    ev["commitment_source_for_classifier"] = classifier.commitment_source_for_classifier

    # V2 categories
    ev["v2_category"] = signals.v2_category
    ev["legacy_compat_category"] = signals.legacy_compat_category
    ev["category"] = signals.v2_category  # primary category field

    # V2 compatibility rollup (NOT primary)
    ev["reasoning_correct_compat"] = signals.reasoning_correct_compat

    # Schema variant tracking
    ev["classifier_schema_variant"] = classifier.classifier_schema_variant
    ev["classifier_prompt_variant"] = classifier.classifier_prompt_variant

    # Backward compat fields
    ev["reasoning_correct"] = signals.reasoning_correct_compat
    ev["alignment"] = {
        "category": signals.v2_category,
        "code_correct": exec_result.get("pass", False),
        "reasoning_correct": signals.reasoning_correct_compat,
    }

    return ev
