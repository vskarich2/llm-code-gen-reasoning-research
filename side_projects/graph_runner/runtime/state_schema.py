"""Typed state schema for the graph runner DAG.

Defines closed TypedDict schemas for all structured state values.
Enforces shape correctness at type-check time (mypy/pyright).
Runtime validation is in state_validation.py.
"""

from __future__ import annotations

from typing import Any, TypedDict


class RoutingDecision(TypedDict):
    """Output of RouteNode: which parse result was selected."""
    selected_source: str        # must be one of VALID_ROUTE_SOURCES
    strict_parse_valid: bool
    recovery_parse_valid: bool
    strict_structurally_valid: bool
    recovery_structurally_valid: bool
    recovery_used: bool
    divergence_detected: bool
    structural_errors: list[str]


class ExecutionResult(TypedDict, total=False):
    """Output of ExecuteNode: test execution outcome."""
    category: str               # must be one of VALID_EXEC_CATEGORIES
    passed: bool
    score: float
    reasons: list[str]


class InvariantRecord(TypedDict):
    """One invariant violation record."""
    stage: str
    type: str
    severity: str
    message: str


class OracleSummary(TypedDict, total=False):
    """Output of OracleAggregationNode."""
    primary: dict[str, Any]
    all: dict[str, dict[str, Any]]
    oracle_correct: bool | None
    reasoning_truth: str | None
    primary_id: str


class ClassifierSummary(TypedDict, total=False):
    """Output of ClassifierAggregationNode."""
    primary: Any
    all: dict[str, dict[str, Any]]
    canonical_dims: dict[str, str]
    classify_event_id: int | str | None
    primary_id: str


class PipelineState(TypedDict, total=False):
    """Complete DAG state schema.

    total=False means all keys are optional — they are populated
    incrementally as nodes execute. Validation functions check
    required keys at each stage boundary.
    """
    # Seed keys (provided by caller)
    case: dict[str, Any]
    condition: str
    model: str
    config: Any
    retry_context: dict[str, Any] | None

    # PromptBuildNode
    prompt: str
    prompt_meta: dict[str, Any]

    # GenerateNode
    raw_response: str
    gen_event_id: int | str

    # ParseNode
    strict_parse: Any
    recovery_parse: Any
    format_parse: Any

    # RouteNode
    parsed_generation: Any
    routing: RoutingDecision
    parse_mode: str
    retry_eligible: bool

    # NormalizeNode
    normalized_reasoning: Any

    # ReconstructNode
    recon: Any
    reconstructed_code: str
    artifact_id: str

    # Oracle slot
    oracle_results: dict[str, dict[str, Any]]

    # OracleAggregationNode
    oracle_summary: OracleSummary

    # Classifier slot
    classifier_results: dict[str, dict[str, Any]]

    # ClassifierAggregationNode
    classifier_summary: ClassifierSummary
    classify_event_id: int | str | None

    # ASTNode
    ast_result: Any

    # ExecuteNode
    execution_result: dict[str, Any]
    passed: bool

    # SpecOracleNode
    spec_oracle_result: dict[str, Any] | None

    # MetricsNode
    signals: Any
    disagreement: dict[str, Any]
    evaluation: dict[str, Any]

    # AssembleNode
    final_result: dict[str, Any]

    # LogNode
    log_status: str

    # Invariant telemetry
    _invariants: list[InvariantRecord]
