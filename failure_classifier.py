"""Heuristic failure classifier for T3 benchmark.

Classifies execution failures into structured types using ONLY
error_obj and critique signals. No ground truth access (no case metadata).

Priority rules:
  1. critique.failure_type + keyword match on root_cause/invariant (conf 0.8)
  2. error_obj.category mapping (conf 0.5)
  3. Keyword scan on error_obj.reasons (conf 0.3)
  4. Fallback → UNKNOWN (conf 0.0)
"""

import re

FAILURE_TYPES = (
    "TEMPORAL_ORDERING",
    "HIDDEN_DEPENDENCY",
    "PARTIAL_STATE_UPDATE",
    "INVARIANT_VIOLATION",
    "RETRY_LOGIC_BUG",
    "LOGGING_INCONSISTENCY",
    "CONFOUNDING_LOGIC",
    "EDGE_CASE_MISSED",
    "UNKNOWN",
)

FAILURE_TYPE_SET = frozenset(FAILURE_TYPES)

_CRITIQUE_KEYWORDS = {
    "TEMPORAL_ORDERING": ["order", "before", "after", "timing", "sequence", "first", "stale"],
    "HIDDEN_DEPENDENCY": ["depend", "import", "hidden", "missing", "undefined", "not defined"],
    "PARTIAL_STATE_UPDATE": ["partial", "incomplete", "subset", "some but not all", "both"],
    "INVARIANT_VIOLATION": ["invariant", "conserv", "balance", "consistent", "atomic", "rollback"],
    "RETRY_LOGIC_BUG": ["retry", "duplic", "idempot", "repeat", "twice", "already"],
    "LOGGING_INCONSISTENCY": ["log", "side effect", "record", "reasoning_evaluator_audit", "trace"],
    "EDGE_CASE_MISSED": ["edge", "boundary", "null", "empty", "zero", "none"],
}

_CATEGORY_MAP = {
    "syntax": ("EDGE_CASE_MISSED", 0.5),
    "load": ("HIDDEN_DEPENDENCY", 0.5),
}

_RUNTIME_KEYWORDS = {
    "NameError": "HIDDEN_DEPENDENCY",
    "ImportError": "HIDDEN_DEPENDENCY",
    "AttributeError": "HIDDEN_DEPENDENCY",
    "KeyError": "PARTIAL_STATE_UPDATE",
    "IndexError": "EDGE_CASE_MISSED",
    "TypeError": "CONFOUNDING_LOGIC",
    "ValueError": "EDGE_CASE_MISSED",
}


def classify_failure(error_obj: dict, critique: dict | None) -> dict:
    """Classify a failure. No ground truth leakage.

    Args:
        error_obj: From _build_error_object (has category, message, reasons)
        critique: From _call_critique (may be None or have _valid=False)

    Returns dict with ALL fields always present (never null).
    """
    # Rule 1: Critique keyword match (highest confidence)
    if critique and critique.get("_valid", True) and critique.get("_valid") is not False:
        root_cause = (critique.get("root_cause") or "").lower()
        invariant = (critique.get("invariant_violated") or "").lower()
        combined = root_cause + " " + invariant

        for ftype, keywords in _CRITIQUE_KEYWORDS.items():
            matched = [kw for kw in keywords if kw in combined]
            if matched:
                return _result(ftype, 0.8, "rule1_critique_keyword",
                               critique.get("failure_type"), error_obj.get("category", ""),
                               matched)

    # Rule 2: Error category mapping
    category = error_obj.get("category", "")
    if category in _CATEGORY_MAP:
        ftype, conf = _CATEGORY_MAP[category]
        return _result(ftype, conf, "rule2_error_category",
                       critique.get("failure_type") if critique else None,
                       category, [category])

    if category == "runtime":
        message = error_obj.get("message", "")
        for err_type, ftype in _RUNTIME_KEYWORDS.items():
            if err_type in message:
                return _result(ftype, 0.5, "rule2_runtime_keyword",
                               critique.get("failure_type") if critique else None,
                               category, [err_type])
        return _result("CONFOUNDING_LOGIC", 0.4, "rule2_runtime_default",
                       critique.get("failure_type") if critique else None,
                       category, [])

    # Rule 3: Keyword scan on error_obj.reasons
    reasons_text = " ".join(error_obj.get("reasons", [])).lower()
    message_text = (error_obj.get("message") or "").lower()
    combined_text = reasons_text + " " + message_text

    if combined_text.strip():
        for ftype, keywords in _CRITIQUE_KEYWORDS.items():
            matched = [kw for kw in keywords if kw in combined_text]
            if matched:
                return _result(ftype, 0.3, "rule3_reason_keyword",
                               critique.get("failure_type") if critique else None,
                               category, matched)

    # Rule 4: UNKNOWN fallback
    return _result("UNKNOWN", 0.0, "rule4_fallback",
                   critique.get("failure_type") if critique else None,
                   category, [])


def _result(failure_type, confidence, rule_path, critique_failure_type,
            error_category, matched_keywords):
    """Build result dict. All fields always present."""
    return {
        "failure_type_final": failure_type,
        "critique_failure_type": critique_failure_type,
        "error_category": error_category,
        "matched_keywords": matched_keywords,
        "classifier_rule_path": rule_path,
        "classifier_confidence": confidence,
    }
