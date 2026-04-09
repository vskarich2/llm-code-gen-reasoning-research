"""Full-state invariant validation — runs after every node.

Checks required fields, cross-field relationships, and stage transitions.
Logs violations AND appends to state[KEY_INVARIANTS].
Does NOT raise exceptions — warnings only.
"""

from __future__ import annotations

from typing import Any

from core.logging_.node_logger import log_node_warning
from side_projects.graph_runner.constants import (
    FIELD_PRIMARY,
    FIELD_SELECTED_SOURCE,
    KEY_ARTIFACT_ID,
    KEY_AST_RESULT,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CONDITION,
    KEY_DISAGREEMENT,
    KEY_EVALUATION,
    KEY_EXECUTION_RESULT,
    KEY_INVARIANTS,
    KEY_NORMALIZED_REASONING,
    KEY_ORACLE_RESULTS,
    KEY_ORACLE_SUMMARY,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_PASSED,
    KEY_PROMPT,
    KEY_RAW_RESPONSE,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    KEY_ROUTING,
    KEY_SIGNALS,
    KEY_SPEC_ORACLE_RESULT,
    KEY_STRICT_PARSE,
    PARSE_MODE_FAILED,
    PARSE_MODE_RECOVERED,
    PARSE_MODE_STRICT,
    RECON_SUCCESS,
    ROUTE_SOURCE_NONE,
    ROUTE_SOURCE_RECOVERY,
    ROUTE_SOURCE_STRICT,
    VALID_PARSE_MODES,
    VALID_ROUTE_SOURCES,
    EXEC_KEY_EXECUTION_CATEGORY,
    EXEC_KEY_PASS,
    VALID_EXEC_CATEGORIES,
    INV_MISSING_PARSED,
    INV_EMPTY_CODE,
    INV_MISSING_EXECUTION,
    INV_INVALID_TRANSITION,
)


# ============================================================
# REQUIRED FIELDS BY STAGE
# ============================================================

REQUIRED_FIELDS_BY_STAGE: dict[str, frozenset[str]] = {
    "PromptBuildNode": frozenset({KEY_PROMPT}),
    "GenerateNode": frozenset({KEY_RAW_RESPONSE}),
    "ParseNode": frozenset({KEY_STRICT_PARSE}),
    "RouteNode": frozenset({
        KEY_PARSED_GENERATION, KEY_ROUTING, KEY_PARSE_MODE,
    }),
    "NormalizeNode": frozenset({KEY_NORMALIZED_REASONING}),
    "ReconstructNode": frozenset({
        KEY_RECON, KEY_RECONSTRUCTED_CODE, KEY_ARTIFACT_ID,
    }),
    "ASTNode": frozenset({KEY_AST_RESULT}),
    "InlineOracleNode": frozenset({KEY_ORACLE_RESULTS}),
    "OracleAggregationNode": frozenset({KEY_ORACLE_SUMMARY}),
    "ReasoningClassifierNode": frozenset(),
    "ClassifierAggregationNode": frozenset({KEY_CLASSIFIER_SUMMARY}),
    "ExecuteNode": frozenset({KEY_EXECUTION_RESULT, KEY_PASSED}),
    "SpecOracleNode": frozenset({KEY_SPEC_ORACLE_RESULT}),
    "MetricsNode": frozenset({
        KEY_SIGNALS, KEY_DISAGREEMENT, KEY_EVALUATION,
    }),
}


# ============================================================
# VIOLATION BUILDER
# ============================================================

def build_violation(
    stage: str, inv_type: str, message: str,
) -> dict[str, str]:
    return {
        "stage": stage,
        "type": inv_type,
        "severity": "warning",
        "message": message,
    }


# ============================================================
# CROSS-FIELD CHECKS
# ============================================================

def check_parse_routing_consistency(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """parse_mode and routing.selected_source must agree."""
    if stage != "RouteNode":
        return

    parse_mode = state.get(KEY_PARSE_MODE)
    routing = state.get(KEY_ROUTING)

    if parse_mode is None or routing is None:
        return

    source = getattr(routing, FIELD_SELECTED_SOURCE, None)
    if source is None:
        return

    if parse_mode == PARSE_MODE_FAILED and source != ROUTE_SOURCE_NONE:
        msg = (
            f"parse_mode={parse_mode} but "
            f"routing.selected_source={source} — "
            "failed parse must route to NONE"
        )
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_INVALID_TRANSITION, msg,
        ))

    if parse_mode == PARSE_MODE_STRICT and source != ROUTE_SOURCE_STRICT:
        msg = (
            f"parse_mode={parse_mode} but "
            f"routing.selected_source={source} — "
            "strict parse must route to STRICT"
        )
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_INVALID_TRANSITION, msg,
        ))

    if parse_mode == PARSE_MODE_RECOVERED and source != ROUTE_SOURCE_RECOVERY:
        msg = (
            f"parse_mode={parse_mode} but "
            f"routing.selected_source={source} — "
            "recovered parse must route to RECOVERY"
        )
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_INVALID_TRANSITION, msg,
        ))


def check_parse_generation_presence(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """Non-failed parse_mode requires parsed_generation."""
    if stage != "RouteNode":
        return

    parse_mode = state.get(KEY_PARSE_MODE)
    if parse_mode is not None and parse_mode != PARSE_MODE_FAILED:
        if not state.get(KEY_PARSED_GENERATION):
            msg = (
                f"parse_mode={parse_mode} but "
                "parsed_generation is missing"
            )
            log_node_warning(node=stage, message=msg, state=state)
            violations.append(build_violation(
                stage, INV_MISSING_PARSED, msg,
            ))


def check_reconstruction_consistency(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """Successful recon requires non-empty code and artifact_id."""
    if stage != "ReconstructNode":
        return

    recon = state.get(KEY_RECON)
    code = state.get(KEY_RECONSTRUCTED_CODE, "")
    artifact_id = state.get(KEY_ARTIFACT_ID, "")

    if recon is not None and hasattr(recon, "status"):
        if recon.status == RECON_SUCCESS:
            if not code:
                msg = "recon.status=SUCCESS but reconstructed_code is empty"
                log_node_warning(node=stage, message=msg, state=state)
                violations.append(build_violation(
                    stage, INV_EMPTY_CODE, msg,
                ))
            if not artifact_id:
                msg = "recon.status=SUCCESS but artifact_id is empty"
                log_node_warning(node=stage, message=msg, state=state)
                violations.append(build_violation(
                    stage, INV_EMPTY_CODE, msg,
                ))


def check_execution_result_structure(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """execution_result must have category and pass fields."""
    if stage != "ExecuteNode":
        return

    exec_result = state.get(KEY_EXECUTION_RESULT)
    if not exec_result:
        msg = "execution_result is missing"
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_MISSING_EXECUTION, msg,
        ))
        return

    if EXEC_KEY_EXECUTION_CATEGORY not in exec_result:
        msg = "execution_result missing execution_category"
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_MISSING_EXECUTION, msg,
        ))

    if EXEC_KEY_PASS not in exec_result:
        msg = "execution_result missing pass field"
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_MISSING_EXECUTION, msg,
        ))

    cat = exec_result.get(EXEC_KEY_EXECUTION_CATEGORY)
    if cat is not None and cat not in VALID_EXEC_CATEGORIES:
        msg = f"execution_category={cat!r} not in VALID_EXEC_CATEGORIES"
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_INVALID_TRANSITION, msg,
        ))


def check_oracle_summary_structure(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """oracle_summary must have primary field."""
    if stage != "OracleAggregationNode":
        return

    summary = state.get(KEY_ORACLE_SUMMARY)
    if not summary:
        return

    if FIELD_PRIMARY not in summary:
        msg = "oracle_summary missing primary field"
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_INVALID_TRANSITION, msg,
        ))


def check_classifier_summary_structure(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """classifier_summary must have primary field."""
    if stage != "ClassifierAggregationNode":
        return

    summary = state.get(KEY_CLASSIFIER_SUMMARY)
    if not summary:
        return

    if FIELD_PRIMARY not in summary:
        msg = "classifier_summary missing primary field"
        log_node_warning(node=stage, message=msg, state=state)
        violations.append(build_violation(
            stage, INV_INVALID_TRANSITION, msg,
        ))


# ============================================================
# REQUIRED FIELDS CHECK
# ============================================================

def check_required_fields(
    state: dict[str, Any],
    stage: str,
    violations: list[dict[str, str]],
) -> None:
    """Verify all required fields for this stage are present."""
    required = REQUIRED_FIELDS_BY_STAGE.get(stage)
    if required is None:
        return

    for key in required:
        if key not in state or state[key] is None:
            msg = f"required field {key!r} missing after {stage}"
            log_node_warning(node=stage, message=msg, state=state)
            violations.append(build_violation(
                stage, INV_MISSING_PARSED, msg,
            ))


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def validate_full_state(
    state: dict[str, Any], stage: str,
) -> None:
    """Validate full pipeline state after a node completes.

    Checks required fields, cross-field relationships, and
    stage transition invariants. Logs violations and appends
    them to state[KEY_INVARIANTS]. Does not raise.
    """
    violations: list[dict[str, str]] = []

    check_required_fields(state, stage, violations)
    check_parse_routing_consistency(state, stage, violations)
    check_parse_generation_presence(state, stage, violations)
    check_reconstruction_consistency(state, stage, violations)
    check_execution_result_structure(state, stage, violations)
    check_oracle_summary_structure(state, stage, violations)
    check_classifier_summary_structure(state, stage, violations)

    if violations:
        state.setdefault(KEY_INVARIANTS, []).extend(violations)
