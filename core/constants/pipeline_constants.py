"""Canonical pipeline constants — single source of truth for all string keys.

Every state key, parse mode, critique type, and warning message used across
the pipeline MUST be defined here. Raw string literals for these values are
forbidden in pipeline code.

This module contains ONLY frozen values. No mutable state. No functions.
No imports beyond typing.
"""

from typing import Final, FrozenSet


# ============================================================
# STATE KEYS — DAG input/output keys
# ============================================================

# Seeded at entry (not produced by any node)
KEY_CASE: Final[str] = "case"
KEY_CONDITION: Final[str] = "condition"
KEY_MODEL: Final[str] = "model"
KEY_CONFIG: Final[str] = "config"
KEY_RETRY_CONTEXT: Final[str] = "retry_context"

# PromptBuildNode
KEY_PROMPT: Final[str] = "prompt"
KEY_PROMPT_META: Final[str] = "prompt_meta"

# GenerateNode
KEY_RAW_RESPONSE: Final[str] = "raw_response"
KEY_GEN_EVENT_ID: Final[str] = "gen_event_id"

# ParseNode
KEY_STRICT_PARSE: Final[str] = "strict_parse"
KEY_RECOVERY_PARSE: Final[str] = "recovery_parse"
KEY_FORMAT_PARSE: Final[str] = "format_parse"

# RouteNode
KEY_PARSED_GENERATION: Final[str] = "parsed_generation"
KEY_ROUTING: Final[str] = "routing"
KEY_PARSE_MODE: Final[str] = "parse_mode"
KEY_RETRY_ELIGIBLE: Final[str] = "retry_eligible"

# OracleNode (slot output via aggregation)
KEY_ORACLE_RESULTS: Final[str] = "oracle_results"
KEY_ORACLE_SUMMARY: Final[str] = "oracle_summary"

# NormalizeNode
KEY_NORMALIZED_REASONING: Final[str] = "normalized_reasoning"

# ReconstructNode
KEY_RECON: Final[str] = "recon"
KEY_RECONSTRUCTED_CODE: Final[str] = "reconstructed_code"
KEY_ARTIFACT_ID: Final[str] = "artifact_id"

# ClassifierNode (slot output via aggregation)
KEY_CLASSIFIER_RESULTS: Final[str] = "classifier_results"
KEY_CLASSIFIER_SUMMARY: Final[str] = "classifier_summary"
KEY_CLASSIFY_EVENT_ID: Final[str] = "classify_event_id"

# ASTNode
KEY_AST_RESULT: Final[str] = "ast_result"

# ExecuteNode
KEY_EXECUTION_RESULT: Final[str] = "execution_result"
KEY_PASSED: Final[str] = "passed"

# SpecOracleNode
KEY_SPEC_ORACLE_RESULT: Final[str] = "spec_oracle_result"

# MetricsNode
KEY_SIGNALS: Final[str] = "signals"
KEY_DISAGREEMENT: Final[str] = "disagreement"
KEY_EVALUATION: Final[str] = "evaluation"

# AssembleNode
KEY_FINAL_RESULT: Final[str] = "final_result"

# LogNode
KEY_LOG_STATUS: Final[str] = "log_status"


# ============================================================
# RETRY CONTEXT KEYS — fields inside retry_context dict
# ============================================================

KEY_ATTEMPT_INDEX: Final[str] = "attempt_index"
KEY_PREV_RAW: Final[str] = "prev_raw"
KEY_PREV_CODE: Final[str] = "prev_code"
KEY_TEST_FEEDBACK: Final[str] = "test_feedback"
KEY_CRITIQUE_TEXT: Final[str] = "critique_text"
KEY_DEPTH_HINT: Final[str] = "depth_hint"
KEY_CLASSIFIER_HINT: Final[str] = "classifier_hint"


# ============================================================
# PARSE MODES — values for KEY_PARSE_MODE
# ============================================================

PARSE_MODE_STRICT: Final[str] = "strict"
PARSE_MODE_RECOVERED: Final[str] = "recovered"
PARSE_MODE_FAILED: Final[str] = "failed"

VALID_PARSE_MODES: Final[FrozenSet[str]] = frozenset({
    PARSE_MODE_STRICT,
    PARSE_MODE_RECOVERED,
    PARSE_MODE_FAILED,
})


# ============================================================
# CRITIQUE TYPES — values for ConditionPolicy.critique_type
# ============================================================

CRITIQUE_NONE: Final[str] = "none"
CRITIQUE_BARE_RETRY: Final[str] = "bare_retry"
CRITIQUE_STRICT: Final[str] = "strict"
CRITIQUE_MODERATE: Final[str] = "moderate"
CRITIQUE_AGGRESSIVE: Final[str] = "aggressive"
CRITIQUE_REASONING_ONLY: Final[str] = "reasoning_only"
CRITIQUE_TEST_FEEDBACK: Final[str] = "test_feedback"
CRITIQUE_ADAPTIVE: Final[str] = "adaptive"

VALID_CRITIQUE_TYPES: Final[FrozenSet[str]] = frozenset({
    CRITIQUE_NONE,
    CRITIQUE_BARE_RETRY,
    CRITIQUE_STRICT,
    CRITIQUE_MODERATE,
    CRITIQUE_AGGRESSIVE,
    CRITIQUE_REASONING_ONLY,
    CRITIQUE_TEST_FEEDBACK,
    CRITIQUE_ADAPTIVE,
})

# Critique types that require root_cause and fix_strategy to be non-empty.
# If these fields are absent, should_continue() MUST return False.
CRITIQUE_REQUIRES_REASONING: Final[FrozenSet[str]] = frozenset({
    CRITIQUE_STRICT,
    CRITIQUE_MODERATE,
    CRITIQUE_AGGRESSIVE,
    CRITIQUE_REASONING_ONLY,
    CRITIQUE_ADAPTIVE,
})


# ============================================================
# NODE TYPES — pure vs effect classification
# ============================================================

NODE_TYPE_PURE: Final[str] = "pure"
NODE_TYPE_EFFECT: Final[str] = "effect"

VALID_NODE_TYPES: Final[FrozenSet[str]] = frozenset({
    NODE_TYPE_PURE,
    NODE_TYPE_EFFECT,
})


# ============================================================
# SLOT NAMES — oracle and classifier slot identifiers
# ============================================================

SLOT_ORACLE: Final[str] = "oracle"
SLOT_CLASSIFIER: Final[str] = "classifier"

VALID_SLOTS: Final[FrozenSet[str]] = frozenset({
    SLOT_ORACLE,
    SLOT_CLASSIFIER,
})


# ============================================================
# OUTCOME CLASSES — values for evaluation.outcome_class
# ============================================================

OUTCOME_INTERPRETABLE_SUCCESS: Final[str] = "interpretable_success"
OUTCOME_LUCKY_FIX: Final[str] = "lucky_fix"
OUTCOME_LEG: Final[str] = "LEG"
OUTCOME_COHERENT_INCORRECT: Final[str] = "coherent_incorrect"
OUTCOME_INCOHERENT_INCORRECT: Final[str] = "incoherent_incorrect"
OUTCOME_SERIALIZATION_FAILURE: Final[str] = "serialization_failure"
OUTCOME_ORACLE_NOT_AVAILABLE: Final[str] = "oracle_not_available"
OUTCOME_CLASSIFIER_NOT_RUN: Final[str] = "classifier_not_run"
OUTCOME_UNCLASSIFIED: Final[str] = "unclassified"


# ============================================================
# EXECUTION CATEGORIES — values for execution_result.execution_category
# ============================================================

EXEC_SUCCESS: Final[str] = "EXECUTION_SUCCESS"
EXEC_SYNTAX_FAILURE: Final[str] = "SYNTAX_FAILURE"
EXEC_STRUCTURAL_FAILURE: Final[str] = "STRUCTURAL_FAILURE"
EXEC_INVARIANT_FAILURE: Final[str] = "INVARIANT_FAILURE"


# ============================================================
# ORACLE LABELS — values for oracle_result.reasoning_truth
# ============================================================

ORACLE_CORRECT: Final[str] = "CORRECT"
ORACLE_PARTIAL: Final[str] = "PARTIAL"
ORACLE_WRONG: Final[str] = "WRONG"
ORACLE_UNJUDGABLE: Final[str] = "UNJUDGABLE"

VALID_ORACLE_LABELS: Final[FrozenSet[str]] = frozenset({
    ORACLE_CORRECT,
    ORACLE_PARTIAL,
    ORACLE_WRONG,
    ORACLE_UNJUDGABLE,
})


# ============================================================
# CLASSIFIER DIMENSIONS — dimension keys and valid values
# ============================================================

DIM_REASONING_INTERNAL_CONSISTENCY: Final[str] = "reasoning_internal_consistency"
DIM_COMMITMENTS_INTERNAL_CONSISTENCY: Final[str] = "commitments_internal_consistency"
DIM_COMMITMENTS_CODE_CONSISTENCY: Final[str] = "commitments_code_consistency"
DIM_REASONING_CODE_ALIGNMENT: Final[str] = "reasoning_code_alignment"
DIM_COMMITMENTS_EXTRACTED: Final[str] = "commitments_extracted"
DIM_COMMITMENTS_SATISFIED: Final[str] = "commitments_satisfied"

CLASSIFIER_V3_CORRECT: Final[str] = "CORRECT"
CLASSIFIER_V3_INCORRECT: Final[str] = "INCORRECT"

VALID_CLASSIFIER_V3_VALUES: Final[FrozenSet[str]] = frozenset({
    CLASSIFIER_V3_CORRECT,
    CLASSIFIER_V3_INCORRECT,
})

CLASSIFIER_V2_CORRECT: Final[str] = "CORRECT"
CLASSIFIER_V2_PARTIAL: Final[str] = "PARTIAL"
CLASSIFIER_V2_WRONG: Final[str] = "WRONG"

VALID_CLASSIFIER_V2_VALUES: Final[FrozenSet[str]] = frozenset({
    CLASSIFIER_V2_CORRECT,
    CLASSIFIER_V2_PARTIAL,
    CLASSIFIER_V2_WRONG,
})


# ============================================================
# RECONSTRUCTION STATUS — values for recon.status
# ============================================================

RECON_SUCCESS: Final[str] = "SUCCESS"
RECON_MISSING_FILES: Final[str] = "RECON_MISSING_FILES"
RECON_EMPTY_FILE: Final[str] = "RECON_EMPTY_FILE"
RECON_INVALID_CODE: Final[str] = "RECON_INVALID_CODE"
RECON_SENTINEL_MISMATCH: Final[str] = "RECON_SENTINEL_MISMATCH"


# ============================================================
# SPEC ORACLE DEPTHS — values for spec_oracle_result.llm_depth.depth
# ============================================================

DEPTH_A: Final[str] = "A"
DEPTH_B: Final[str] = "B"
DEPTH_C: Final[str] = "C"
DEPTH_D: Final[str] = "D"
DEPTH_F: Final[str] = "F"
DEPTH_UNKNOWN: Final[str] = "unknown"


# ============================================================
# WARNING MESSAGES — structured degradation signals
# ============================================================

WARNING_MISSING_ROOT_CAUSE: Final[str] = (
    "WARNING: root_cause not populated — "
    "critique generation will be empty"
)
WARNING_MISSING_FIX_STRATEGY: Final[str] = (
    "WARNING: fix_strategy not populated — "
    "critique generation will be empty"
)
WARNING_EMPTY_CRITIQUE: Final[str] = (
    "WARNING: critique not populated — "
    "retry prompt will contain no feedback"
)
WARNING_DEGENERATE_RETRY: Final[str] = (
    "WARNING: reasoning fields missing with critique_type "
    "that requires them — aborting retry"
)
WARNING_PARSE_FAILED_NO_RETRY: Final[str] = (
    "WARNING: parse_mode=failed — no executable artifact, "
    "aborting retry"
)
WARNING_MISSING_SPEC_ORACLE: Final[str] = (
    "WARNING: spec_oracle_result is None — "
    "depth hint will not be generated"
)
WARNING_NODE_MISSING_INPUT: Final[str] = (
    "ERROR: node '{node}' missing required input key '{key}'"
)
WARNING_NODE_EXTRA_OUTPUT: Final[str] = (
    "ERROR: node '{node}' produced undeclared output key '{key}'"
)
WARNING_NODE_MISSING_OUTPUT: Final[str] = (
    "ERROR: node '{node}' did not produce declared output key '{key}'"
)
WARNING_STATE_KEY_OVERWRITE: Final[str] = (
    "ERROR: state key '{key}' already exists — "
    "append-only violation by node '{node}'"
)


# ============================================================
# INVARIANT VIOLATION TYPES — telemetry for pipeline validation
# ============================================================

INV_MISSING_PROMPT: Final[str] = "MISSING_PROMPT"
INV_MISSING_PARSED_GENERATION: Final[str] = "MISSING_PARSED_GENERATION"
INV_MISSING_ROUTING: Final[str] = "MISSING_ROUTING"
INV_EMPTY_RECONSTRUCTED_CODE: Final[str] = "EMPTY_RECONSTRUCTED_CODE"
INV_EMPTY_ARTIFACT_ID: Final[str] = "EMPTY_ARTIFACT_ID"
INV_RECON_SUCCESS_BUT_EMPTY: Final[str] = "RECON_SUCCESS_BUT_EMPTY_CODE"
INV_MISSING_CLASSIFIER_SUMMARY: Final[str] = "MISSING_CLASSIFIER_SUMMARY"
INV_MISSING_CLASSIFIER_PRIMARY: Final[str] = "MISSING_CLASSIFIER_PRIMARY"
INV_MISSING_EXECUTION_RESULT: Final[str] = "MISSING_EXECUTION_RESULT"
INV_MISSING_EXECUTION_CATEGORY: Final[str] = "MISSING_EXECUTION_CATEGORY"
INV_MISSING_EXECUTION_PASS: Final[str] = "MISSING_EXECUTION_PASS"
INV_MISSING_EVALUATION: Final[str] = "MISSING_EVALUATION"
INV_MISSING_SIGNALS: Final[str] = "MISSING_SIGNALS"
INV_MISSING_ORACLE_SUMMARY: Final[str] = "MISSING_ORACLE_SUMMARY"
INV_EMPTY_CRITIQUE: Final[str] = "EMPTY_CRITIQUE"
INV_INVALID_STATE_TRANSITION: Final[str] = "INVALID_STATE_TRANSITION"

# Internal state key for accumulated invariant violations
KEY_INVARIANTS: Final[str] = "_invariants"


# ============================================================
# LOG LEVELS — canonical level strings
# ============================================================

LOG_INFO: Final[str] = "INFO"
LOG_WARNING: Final[str] = "WARNING"
LOG_ERROR: Final[str] = "ERROR"


# ============================================================
# DDC CASE FAMILIES — used by SpecOracleNode guard
# ============================================================

DDC_FAMILIES: Final[FrozenSet[str]] = frozenset({
    "auth_context_chain",
    "billing_aggregation_chain",
    "config_derivation_chain",
    "event_etl_chain",
    "logging_pipeline_chain",
    "ml_feature_chain",
    "search_index_chain",
    "serialization_pipeline_chain",
})
