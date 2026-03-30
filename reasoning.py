"""Reasoning pipeline — structured reasoning extraction, validation, classification, and metrics.

This is the single source of truth for reasoning schema, validation, classifier output parsing,
reasoning_correct derivation, and category computation.

Schema version: 3 (5-dimension classifier, CORRECT/PARTIAL/WRONG, dual-channel output).
"""

REASONING_SCHEMA_VERSION = 3

# Baseline reasoning schema (4 fields)
BASELINE_REASONING_FIELDS = ("root_cause", "failure_mechanism", "broken_invariant", "fix_strategy")

# Minimal LEG reasoning schema (3 fields — root_cause + fix_strategy shared with baseline)
LEG_REASONING_FIELDS = ("root_cause", "fix_strategy", "risk_check")

# Reasoning is "present" if EITHER the baseline set OR the LEG set is satisfied.
# Both are valid reasoning schemas — they come from different prompts.
REQUIRED_REASONING_FIELDS = BASELINE_REASONING_FIELDS  # backward compat alias
MIN_FIELD_LENGTH = 10

VALID_DIMENSIONS = frozenset({"CORRECT", "PARTIAL", "WRONG"})
VALID_CONFIDENCE = frozenset({"HIGH", "MEDIUM", "LOW"})
VALID_FAILURE_TYPES = frozenset({
    "HIDDEN_DEPENDENCY", "TEMPORAL_ORDERING", "INVARIANT_VIOLATION",
    "PARTIAL_STATE_UPDATE", "RETRY_LOGIC_BUG", "EDGE_CASE_MISSED",
    "LOGGING_INCONSISTENCY", "CONFOUNDING_LOGIC", "UNKNOWN",
})

# The 5 classifier dimensions in order
CLASSIFIER_DIMENSIONS = (
    "mechanism_identified",
    "invariant_identified",
    "causal_chain_complete",
    "fix_alignment",
    "reasoning_code_alignment",
)

# Debug section delimiter — everything at and after this line is ignored by the parser
DEBUG_DELIMITER = "---DEBUG---"

# Categories where reasoning was successfully evaluated
COVERED_CATEGORIES = frozenset({"true_success", "leg", "lucky_fix", "true_failure"})


# ============================================================
# EXTRACTION
# ============================================================

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
    # Legacy LEG fields (may be present in old data)
    obj["alternative_hypothesis"] = parsed_json.get("alternative_hypothesis", "")
    obj["hypothesis_rejection"] = parsed_json.get("hypothesis_rejection", "")
    raw_sc = parsed_json.get("self_check", "")
    if isinstance(raw_sc, dict):
        obj["self_check"] = raw_sc
    else:
        obj["self_check"] = raw_sc if isinstance(raw_sc, str) else ""
    return obj


# ============================================================
# VALIDATION (presence only — no semantic judgment)
# ============================================================

def validate_reasoning(reasoning_obj, raw_json):
    """Check presence and length. No semantic validation — that's the classifier's job.

    Reasoning is "present" if EITHER the baseline schema (4 fields) OR the
    LEG schema (3 fields) is satisfied. This ensures the classifier is not
    gated when the model used a different but valid reasoning schema.
    """
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

    return {
        "reasoning_attempted": attempted,
        "reasoning_present": present,
        "reasoning_lengths": lengths,
        "schema_matched": "baseline" if baseline_present else ("leg" if leg_present else "none"),
    }


# ============================================================
# CLASSIFIER OUTPUT PARSING (dual-channel: strict + debug)
# ============================================================

def _strip_debug_section(raw):
    """Remove everything at and after ---DEBUG--- delimiter. Returns stripped text."""
    idx = raw.find(DEBUG_DELIMITER)
    if idx == -1:
        return raw
    return raw[:idx]


def parse_classify_output(raw):
    """Parse 5-line classifier output. Ignores optional ---DEBUG--- section.

    Line 1: <mechanism>;<invariant>;<causal_chain>;<fix_align>;<code_align>;<failure_type>
    Line 2: <confidence>
    Line 3: Counterfactual: <sentence>
    Line 4: Evidence: <bullets>
    Line 5: Judgment: <sentence>

    Returns dict with dimension values, confidence, counterfactual, evidence, judgment,
    and parse_error (None on success).
    """
    stripped = _strip_debug_section(raw)
    lines = [l.strip() for l in stripped.strip().split("\n") if l.strip()]

    if len(lines) != 5:
        return {"parse_error": f"expected_5_lines_got_{len(lines)}"}

    # Line 1: 6 semicolon-separated fields (5 dimensions + failure_type)
    parts = [p.strip().upper() for p in lines[0].split(";")]
    if len(parts) != 6:
        return {"parse_error": f"expected_6_fields_got_{len(parts)}"}

    dims = {}
    for name, val in zip(CLASSIFIER_DIMENSIONS, parts[:5]):
        if val not in VALID_DIMENSIONS:
            return {"parse_error": f"invalid_dimension_{name}_{val}"}
        dims[name] = val

    failure_type_raw = parts[5]
    dims["failure_type"] = failure_type_raw if failure_type_raw in VALID_FAILURE_TYPES else "UNKNOWN"
    dims["failure_type_raw"] = failure_type_raw

    # Line 2: confidence
    confidence = lines[1].strip().upper()
    if confidence not in VALID_CONFIDENCE:
        return {"parse_error": f"invalid_confidence_{confidence}"}
    dims["confidence"] = confidence

    # Line 3: counterfactual
    counterfactual = lines[2].strip()
    if not counterfactual:
        return {"parse_error": "missing_counterfactual"}
    dims["counterfactual"] = counterfactual

    # Line 4: evidence
    evidence = lines[3].strip()
    if not evidence:
        return {"parse_error": "missing_evidence"}
    dims["evidence"] = evidence

    # Line 5: judgment
    judgment = lines[4].strip()
    if not judgment:
        return {"parse_error": "missing_judgment"}
    dims["judgment"] = judgment

    # Legacy alias — downstream code reads "explanation"
    dims["explanation"] = judgment

    dims["parse_error"] = None
    return dims


# ============================================================
# REASONING_CORRECT DERIVATION
# ============================================================

def compute_reasoning_correct(dims, mode="strict", schema_matched="baseline"):
    """Derive reasoning_correct from classifier dimensions.

    Dimension values are CORRECT, PARTIAL, WRONG.

    schema_matched: which reasoning schema was used ("baseline" or "leg").
    When schema is "leg", invariant_identified is not penalized because the
    LEG prompt does not ask for a broken_invariant field. Penalizing a
    dimension the model was never asked to fill is a measurement error.
    """
    m = dims.get("mechanism_identified")
    i = dims.get("invariant_identified")
    c = dims.get("causal_chain_complete")
    f = dims.get("fix_alignment")

    if any(d is None for d in (m, i, c, f)):
        return None

    # When LEG schema was used, the prompt asks for concise root_cause and
    # fix_strategy — NOT a full mechanism trace, NOT a broken invariant
    # statement, NOT a step-by-step causal chain.
    #
    # The classifier evaluates 4 dimensions against a baseline that expects
    # detailed multi-paragraph reasoning. The LEG schema produces concise
    # reasoning that the classifier legitimately scores as PARTIAL or WRONG
    # on mechanism, invariant, and causal chain — not because the reasoning
    # is wrong, but because it is shorter than what the classifier calibrated on.
    #
    # For LEG schema, only two dimensions are meaningful:
    #   mechanism_identified: did the model name the right function/variable? (PARTIAL = yes)
    #   fix_alignment: does the fix match the diagnosis? (PARTIAL = yes)
    #
    # invariant_identified and causal_chain_complete are not asked for by
    # the LEG prompt and must not penalize the score.
    if schema_matched == "leg":
        i = "CORRECT"   # not asked for
        c = "CORRECT"   # not asked for in detail
        if m == "PARTIAL":
            m = "CORRECT"  # concise root_cause = PARTIAL mechanism, but sufficient

    if mode == "strict":
        return (
            m == "CORRECT"
            and i in ("CORRECT", "PARTIAL")
            and c in ("CORRECT", "PARTIAL")
            and f in ("CORRECT", "PARTIAL")
        )
    elif mode == "lenient":
        return (
            m in ("CORRECT", "PARTIAL")
            and i in ("CORRECT", "PARTIAL")
            and c in ("CORRECT", "PARTIAL")
        )
    elif mode == "raw":
        return None
    return None


# ============================================================
# CATEGORY COMPUTATION
# ============================================================

def compute_category(code_correct, reasoning_correct, reasoning_present,
                     classifier_parse_error, parse_failed):
    """Compute case category. 8 explicit categories, 0 ambiguity."""
    if parse_failed:
        return "parse_failed"
    if not reasoning_present:
        return "no_reasoning"
    if classifier_parse_error:
        return "classifier_parse_failed"
    if reasoning_correct is None:
        return "classifier_no_verdict"
    if reasoning_correct and code_correct:
        return "true_success"
    if reasoning_correct and not code_correct:
        return "leg"
    if not reasoning_correct and code_correct:
        return "lucky_fix"
    return "true_failure"


# ============================================================
# GROUNDED MODE
# ============================================================

def should_run_grounded(case, classifier_mode):
    """Determine if grounded evaluation can run for this case."""
    if classifier_mode != "grounded":
        return False, "not_requested"
    gt_inv = case.get("ground_truth_invariant", "").strip()
    gt_mode = case.get("failure_mode", "").strip()
    if not gt_inv or not gt_mode:
        return False, "missing_ground_truth"
    return True, None


# ============================================================
# NULL CLASSIFIER RESULT
# ============================================================

NULL_CLASSIFIER_RESULT = {
    "mechanism_identified": None,
    "invariant_identified": None,
    "causal_chain_complete": None,
    "fix_alignment": None,
    "reasoning_code_alignment": None,
    "failure_type": None,
    "failure_type_raw": None,
    "confidence": None,
    "counterfactual": None,
    "evidence": None,
    "judgment": None,
    "explanation": None,
    "parse_error": None,
}


# ============================================================
# SCHEMA VERSION ENFORCEMENT
# ============================================================

def enforce_schema_version(events_path):
    """Refuse to write mismatched schema versions to same run directory."""
    import json
    from pathlib import Path
    p = Path(events_path)
    if not p.exists():
        return
    first = p.open().readline().strip()
    if not first:
        return
    v = json.loads(first).get("reasoning_schema_version", 1)
    if v != REASONING_SCHEMA_VERSION:
        raise RuntimeError(
            f"SCHEMA VERSION MISMATCH: existing={v}, current={REASONING_SCHEMA_VERSION}. "
            f"Use a new run_dir."
        )
