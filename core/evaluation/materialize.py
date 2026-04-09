"""Metric materialization layer.

Produces a flat DataFrame with one row per attempt from events.jsonl.
All evaluation axes are read directly from logged fields — no recomputation.

Handles both old events (fields in payload) and new events (dedicated sections).
"""

import json
import logging
from pathlib import Path

import pandas as pd

_log = logging.getLogger("t3.materialize")


def build_attempt_table(events_path: Path) -> pd.DataFrame:
    """Build canonical flat analysis table from an events.jsonl file.

    One row per case.end event. All evaluation axes available as columns.
    outcome_class is read directly when present, never recomputed.

    Args:
        events_path: Path to events.jsonl file.

    Returns:
        DataFrame with standardized columns.
    """
    rows = []

    for line in events_path.open():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            break

        if e.get("event_type") != "case.end":
            continue

        row = _extract_row(e)
        if row is not None:
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df


def build_attempt_table_from_dir(run_dir: Path) -> pd.DataFrame:
    """Build table from all worker events in a run directory."""
    rows = []
    for ef in sorted(run_dir.rglob("*/events.jsonl")):
        for line in ef.open():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                break
            if e.get("event_type") != "case.end":
                continue
            row = _extract_row(e)
            if row is not None:
                rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def _extract_row(event: dict) -> dict | None:
    """Extract one row from a case.end event.

    Handles both old format (payload-only) and new format (dedicated sections).
    """
    payload = event.get("payload", {})
    execution = event.get("execution", {})
    reasoning = event.get("reasoning", {})

    # New dedicated sections (may be absent in old events)
    reconstruction = event.get("reconstruction") or payload.get("reconstruction") or {}
    classification = event.get("classification") or {}
    evaluation = event.get("evaluation") or {}
    ast_eval = event.get("ast_eval") or payload.get("ast_eval") or {}

    # ── Identity fields ──
    case_id = event.get("case_id") or event.get("context", {}).get("case_id")
    model = event.get("model")
    trial = event.get("trial")
    condition = payload.get("retry_mode") or event.get("condition") or event.get("context", {}).get("condition")
    attempt = event.get("attempt", 0)

    if not case_id:
        return None

    # ── Serialization axis ──
    # New format: read from evaluation section
    serialization_success = evaluation.get("serialization_success")
    serialization_failure_type = evaluation.get("serialization_failure_type")

    # Fallback for old events: infer from reconstruction status
    if serialization_success is None:
        recon_status = payload.get("reconstruction_status", "")
        parse_status = payload.get("v2_parse_tiers", {}).get("exec_parse_valid")
        if recon_status == "SUCCESS":
            serialization_success = True
        elif parse_status is False or recon_status in ("RECON_MISSING_FILES", "RECON_INVALID_CODE"):
            serialization_success = False
            serialization_failure_type = "recon_failure" if recon_status else "parser_failure"
        else:
            serialization_success = recon_status == "SUCCESS" if recon_status else None

    # ── Execution axis ──
    execution_success = evaluation.get("execution_success")
    execution_category = evaluation.get("execution_category") or payload.get("execution_category")

    if execution_success is None:
        execution_success = bool(execution.get("passed"))

    # ── Reasoning axis ──
    reasoning_consistent = evaluation.get("reasoning_consistent") or evaluation.get("reasoning_consistent")
    commitments_valid = evaluation.get("commitments_valid")
    alignment_positive = evaluation.get("alignment_positive")
    reasoning_sufficient = evaluation.get("reasoning_sufficient")

    # Fallback for old events: read from payload
    if reasoning_consistent is None:
        ric_dim = (classification.get("reasoning_internal_consistency")
                   or classification.get("reasoning_internal_consistency")
                   or payload.get("reasoning_internal_consistency_dim")
                   or payload.get("reasoning_internal_consistency_dim"))
        reasoning_consistent = (ric_dim == "CORRECT") if ric_dim else payload.get("reasoning_consistent") or payload.get("reasoning_consistent")

    if commitments_valid is None:
        comm_dim = classification.get("commitments_satisfied") or payload.get("commitments_satisfied_dim")
        commitments_valid = (comm_dim == "CORRECT") if comm_dim else payload.get("commitments_valid")

    if alignment_positive is None:
        align_dim = classification.get("reasoning_code_alignment") or payload.get("reasoning_code_alignment_dim")
        alignment_positive = (align_dim == "CORRECT") if align_dim else payload.get("alignment_positive")

    if reasoning_sufficient is None:
        if reasoning_consistent is not None and commitments_valid is not None:
            reasoning_sufficient = bool(reasoning_consistent) and bool(commitments_valid)

    # ── Outcome class ──
    outcome_class = evaluation.get("outcome_class")

    # Fallback for old events: read from payload category
    if outcome_class is None:
        v2_cat = payload.get("v2_category") or payload.get("category")
        if v2_cat:
            outcome_class = _map_legacy_category(v2_cat, serialization_success,
                                                  execution_success, reasoning_sufficient)

    # ── LEG ──
    leg = evaluation.get("LEG")
    leg_subtype = evaluation.get("LEG_subtype")

    if leg is None:
        leg = (outcome_class == "LEG") if outcome_class else None

    # ── Reconstruction/parsing ──
    parsing_mode = reconstruction.get("parsing_mode")
    recovery_used = reconstruction.get("recovery_used", False)
    structurally_valid = reconstruction.get("structurally_valid") or reconstruction.get("strict_structurally_valid")
    execution_eligible = reconstruction.get("execution_eligible")
    recon_status = reconstruction.get("recon_status") or payload.get("reconstruction_status")

    # Fallback for old events
    if parsing_mode is None:
        parse_tiers = payload.get("v2_parse_tiers", {})
        if parse_tiers.get("exec_parse_valid"):
            parsing_mode = "strict"
        elif parse_tiers.get("recovery_parse_valid"):
            parsing_mode = "recovery"
        else:
            parsing_mode = "failed" if parse_tiers else None

    # ── AST ──
    ast_status = ast_eval.get("status")
    ast_correct = ast_eval.get("ast_correct")
    ast_score = ast_eval.get("ast_score")

    # ── Classification ──
    classifier_ran = classification.get("classifier_ran")
    commitment_state = classification.get("commitment_state")

    if classifier_ran is None:
        classifier_ran = payload.get("classify_v2_parse_error") is None and (payload.get("reasoning_internal_consistency_dim") is not None or payload.get("reasoning_internal_consistency_dim") is not None)

    if commitment_state is None:
        commitment_state = payload.get("commitment_source_for_classifier") or "none"

    # ── Additional useful fields ──
    score = payload.get("score") or execution.get("score")
    failure_type = payload.get("failure_type") or reasoning.get("failure_type")
    v2_category = payload.get("v2_category") or payload.get("category")

    # ── Artifact ID ──
    artifact_id = (reconstruction.get("artifact_id")
                   or evaluation.get("artifact_id")
                   or classification.get("artifact_id"))

    return {
        # Identity
        "case_id": case_id,
        "model": model,
        "trial": trial,
        "condition": condition,
        "attempt": attempt,

        # Serialization axis
        "serialization_success": serialization_success,
        "serialization_failure_type": serialization_failure_type,

        # Execution axis
        "execution_success": execution_success,
        "execution_category": execution_category,

        # Reasoning axis
        "reasoning_consistent": reasoning_consistent,
        "commitments_valid": commitments_valid,
        "alignment_positive": alignment_positive,
        "reasoning_sufficient": reasoning_sufficient,

        # Outcome
        "outcome_class": outcome_class,
        "LEG": leg,
        "LEG_subtype": leg_subtype,

        # Parsing/reconstruction
        "parsing_mode": parsing_mode,
        "recovery_used": recovery_used,
        "structurally_valid": structurally_valid,
        "execution_eligible": execution_eligible,
        "recon_status": recon_status,

        # AST
        "ast_status": ast_status,
        "ast_correct": ast_correct,
        "ast_score": ast_score,

        # Classification
        "classifier_ran": classifier_ran,
        "commitment_state": commitment_state,

        # Additional
        "score": score,
        "failure_type": failure_type,
        "v2_category": v2_category,
        "artifact_id": artifact_id,
    }


def _map_legacy_category(v2_cat: str, S, E, R) -> str:
    """Map legacy v2_category to outcome_class for old events."""
    cat_map = {
        "interpretable_success": "interpretable_success",
        "full_failure_v2": "reasoning_failure",
        "LEG_v2": "LEG",
        "alignment_failure_pass": "unsupported_success",
        "lucky_fix_v2": "unsupported_success",
        "parser_failure_v2": "serialization_failure",
        "uninterpretable_success": "unsupported_success",
    }
    mapped = cat_map.get(v2_cat)
    if mapped:
        return mapped

    # Fallback: compute from axes
    if S is False:
        return "serialization_failure"
    if S and E and R:
        return "interpretable_success"
    if S and E and not R:
        return "unsupported_success"
    if S and not E and R:
        return "LEG"
    if S and not E and not R:
        return "reasoning_failure"
    return "unknown"
