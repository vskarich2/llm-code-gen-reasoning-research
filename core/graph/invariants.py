"""Pipeline invariant validation — runs after every node.

Checks cross-stage invariants. Logs violations AND stores them in
state["_invariants"] for propagation to the final result.
Does NOT raise exceptions.
"""

from __future__ import annotations

from typing import Any

from core.constants.pipeline_constants import (
    INV_EMPTY_ARTIFACT_ID,
    INV_EMPTY_CRITIQUE,
    INV_EMPTY_RECONSTRUCTED_CODE,
    INV_MISSING_CLASSIFIER_PRIMARY,
    INV_MISSING_CLASSIFIER_SUMMARY,
    INV_MISSING_EVALUATION,
    INV_MISSING_EXECUTION_CATEGORY,
    INV_MISSING_EXECUTION_PASS,
    INV_MISSING_EXECUTION_RESULT,
    INV_MISSING_ORACLE_SUMMARY,
    INV_MISSING_PARSED_GENERATION,
    INV_MISSING_PROMPT,
    INV_MISSING_ROUTING,
    INV_MISSING_SIGNALS,
    INV_RECON_SUCCESS_BUT_EMPTY,
    KEY_ARTIFACT_ID,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CRITIQUE_TEXT,
    KEY_EVALUATION,
    KEY_EXECUTION_RESULT,
    KEY_INVARIANTS,
    KEY_ORACLE_SUMMARY,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_PROMPT,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    KEY_ROUTING,
    KEY_SIGNALS,
    PARSE_MODE_FAILED,
    RECON_SUCCESS,
)
from core.logging_.node_logger import log_node_warning


def _violation(
    stage: str, inv_type: str, message: str,
) -> dict[str, str]:
    """Build a structured violation record."""
    return {
        "stage": stage,
        "type": inv_type,
        "severity": "warning",
        "message": message,
    }


def validate_pipeline_state(
    state: dict[str, Any], stage: str,
) -> None:
    """Validate cross-stage invariants after a node completes.

    Called by GraphRunner after every node execution.
    Logs warnings AND appends violations to state["_invariants"].
    Does not raise.
    """
    violations: list[dict[str, str]] = []

    _validate_prompt(state, stage, violations)
    _validate_parse(state, stage, violations)
    _validate_reconstruct(state, stage, violations)
    _validate_classify(state, stage, violations)
    _validate_execute(state, stage, violations)
    _validate_metrics(state, stage, violations)
    _validate_critique(state, stage, violations)

    if violations:
        state.setdefault(KEY_INVARIANTS, []).extend(violations)


def _warn_and_record(
    stage: str,
    inv_type: str,
    message: str,
    state: dict[str, Any],
    violations: list[dict[str, str]],
) -> None:
    """Log warning AND append to violations list."""
    log_node_warning(node=stage, message=message, state=state)
    violations.append(_violation(stage, inv_type, message))


def _validate_prompt(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "PromptBuildNode":
        return
    if not state.get(KEY_PROMPT):
        _warn_and_record(
            stage, INV_MISSING_PROMPT,
            "Prompt is empty after PromptBuildNode",
            state, violations,
        )


def _validate_parse(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "RouteNode":
        return
    parse_mode = state.get(KEY_PARSE_MODE)
    if parse_mode == PARSE_MODE_FAILED:
        return
    if not state.get(KEY_PARSED_GENERATION):
        _warn_and_record(
            stage, INV_MISSING_PARSED_GENERATION,
            f"parsed_generation missing despite parse_mode={parse_mode!r}",
            state, violations,
        )
    if not state.get(KEY_ROUTING):
        _warn_and_record(
            stage, INV_MISSING_ROUTING,
            f"routing missing despite parse_mode={parse_mode!r}",
            state, violations,
        )


def _validate_reconstruct(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "ReconstructNode":
        return
    code = state.get(KEY_RECONSTRUCTED_CODE, "")
    if not code:
        _warn_and_record(
            stage, INV_EMPTY_RECONSTRUCTED_CODE,
            "Reconstructed code is empty",
            state, violations,
        )
    recon = state.get(KEY_RECON)
    if recon is not None and hasattr(recon, "status"):
        if recon.status == RECON_SUCCESS and not code:
            _warn_and_record(
                stage, INV_RECON_SUCCESS_BUT_EMPTY,
                "Reconstruction status is SUCCESS but code is empty",
                state, violations,
            )
    if not state.get(KEY_ARTIFACT_ID, ""):
        _warn_and_record(
            stage, INV_EMPTY_ARTIFACT_ID,
            "artifact_id is empty after reconstruction",
            state, violations,
        )


def _validate_classify(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "ClassifierAggregationNode":
        return
    summary = state.get(KEY_CLASSIFIER_SUMMARY)
    if not summary:
        _warn_and_record(
            stage, INV_MISSING_CLASSIFIER_SUMMARY,
            "classifier_summary missing",
            state, violations,
        )
    elif not summary.get("primary"):
        _warn_and_record(
            stage, INV_MISSING_CLASSIFIER_PRIMARY,
            "classifier_summary.primary missing",
            state, violations,
        )


def _validate_execute(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "ExecuteNode":
        return
    exec_result = state.get(KEY_EXECUTION_RESULT)
    if not exec_result:
        _warn_and_record(
            stage, INV_MISSING_EXECUTION_RESULT,
            "execution_result missing",
            state, violations,
        )
        return
    if "execution_category" not in exec_result:
        _warn_and_record(
            stage, INV_MISSING_EXECUTION_CATEGORY,
            "execution_result missing execution_category field",
            state, violations,
        )
    if "pass" not in exec_result:
        _warn_and_record(
            stage, INV_MISSING_EXECUTION_PASS,
            "execution_result missing pass field",
            state, violations,
        )


def _validate_metrics(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "MetricsNode":
        return
    if not state.get(KEY_EVALUATION):
        _warn_and_record(
            stage, INV_MISSING_EVALUATION,
            "evaluation dict missing after MetricsNode",
            state, violations,
        )
    if not state.get(KEY_SIGNALS):
        _warn_and_record(
            stage, INV_MISSING_SIGNALS,
            "signals missing after MetricsNode",
            state, violations,
        )
    if not state.get(KEY_ORACLE_SUMMARY):
        _warn_and_record(
            stage, INV_MISSING_ORACLE_SUMMARY,
            "oracle_summary missing at MetricsNode",
            state, violations,
        )


def _validate_critique(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    if stage != "CritiqueNode":
        return
    if state.get(KEY_CRITIQUE_TEXT, "") == "":
        _warn_and_record(
            stage, INV_EMPTY_CRITIQUE,
            "Critique text is empty",
            state, violations,
        )
