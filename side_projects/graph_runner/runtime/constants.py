"""Graph runner constants — single source of truth for all string keys.

Every state key, routing value, node name, and status string used in the
graph runner MUST be defined here. Raw string literals for these values
are forbidden in graph runner code.

Imports pipeline_constants for shared keys. Defines graph-runner-specific
keys that do not belong in the core pipeline constants.
"""

from typing import Final, FrozenSet

# Re-export all pipeline constants so nodes import from one place
from core.constants.pipeline_constants import (
    KEY_ARTIFACT_ID,
    KEY_AST_RESULT,
    KEY_CASE,
    KEY_CLASSIFIER_RESULTS,
    KEY_CLASSIFIER_SUMMARY,
    KEY_CLASSIFY_EVENT_ID,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_CRITIQUE_TEXT,
    KEY_DISAGREEMENT,
    KEY_EVALUATION,
    KEY_EXECUTION_RESULT,
    KEY_FINAL_RESULT,
    KEY_FORMAT_PARSE,
    KEY_GEN_EVENT_ID,
    KEY_INVARIANTS,
    KEY_LOG_STATUS,
    KEY_MODEL,
    KEY_NORMALIZED_REASONING,
    KEY_ORACLE_RESULTS,
    KEY_ORACLE_SUMMARY,
    KEY_PARSE_MODE,
    KEY_PARSED_GENERATION,
    KEY_PASSED,
    KEY_PROMPT,
    KEY_PROMPT_META,
    KEY_RAW_RESPONSE,
    KEY_RECON,
    KEY_RECONSTRUCTED_CODE,
    KEY_RECOVERY_PARSE,
    KEY_RETRY_CONTEXT,
    KEY_RETRY_ELIGIBLE,
    KEY_ROUTING,
    KEY_SIGNALS,
    KEY_SPEC_ORACLE_RESULT,
    KEY_STRICT_PARSE,
    DDC_FAMILIES,
    NODE_TYPE_EFFECT,
    NODE_TYPE_PURE,
    VALID_NODE_TYPES,
)


# ============================================================
# PARSE MODES — closed enum, self-describing values
# ============================================================

PARSE_MODE_STRICT: Final[str] = "PARSE_MODE_STRICT"
PARSE_MODE_RECOVERED: Final[str] = "PARSE_MODE_RECOVERED"
PARSE_MODE_FAILED: Final[str] = "PARSE_MODE_FAILED"

VALID_PARSE_MODES: Final[FrozenSet[str]] = frozenset({
    PARSE_MODE_STRICT,
    PARSE_MODE_RECOVERED,
    PARSE_MODE_FAILED,
})


# ============================================================
# ROUTING SOURCES — closed enum, self-describing values
# ============================================================

ROUTE_SOURCE_STRICT: Final[str] = "ROUTE_SOURCE_STRICT"
ROUTE_SOURCE_RECOVERY: Final[str] = "ROUTE_SOURCE_RECOVERY"
ROUTE_SOURCE_FORMAT: Final[str] = "ROUTE_SOURCE_FORMAT"
ROUTE_SOURCE_NONE: Final[str] = "ROUTE_SOURCE_NONE"

VALID_ROUTE_SOURCES: Final[FrozenSet[str]] = frozenset({
    ROUTE_SOURCE_STRICT,
    ROUTE_SOURCE_RECOVERY,
    ROUTE_SOURCE_FORMAT,
    ROUTE_SOURCE_NONE,
})


# ============================================================
# EXECUTION CATEGORIES — closed enum, self-describing values
# ============================================================

EXEC_SUCCESS: Final[str] = "EXEC_SUCCESS"
EXEC_SYNTAX_ERROR: Final[str] = "EXEC_SYNTAX_ERROR"
EXEC_IMPORT_ERROR: Final[str] = "EXEC_IMPORT_ERROR"
EXEC_RUNTIME_ERROR: Final[str] = "EXEC_RUNTIME_ERROR"
EXEC_TIMEOUT: Final[str] = "EXEC_TIMEOUT"
EXEC_STRUCTURAL_FAILURE: Final[str] = "EXEC_STRUCTURAL_FAILURE"
EXEC_UNKNOWN: Final[str] = "EXEC_UNKNOWN"

VALID_EXEC_CATEGORIES: Final[FrozenSet[str]] = frozenset({
    EXEC_SUCCESS,
    EXEC_SYNTAX_ERROR,
    EXEC_IMPORT_ERROR,
    EXEC_RUNTIME_ERROR,
    EXEC_TIMEOUT,
    EXEC_STRUCTURAL_FAILURE,
    EXEC_UNKNOWN,
})


# ============================================================
# INVARIANT VIOLATION TYPES — closed enum
# ============================================================

INV_MISSING_PARSED: Final[str] = "INV_MISSING_PARSED"
INV_EMPTY_CODE: Final[str] = "INV_EMPTY_CODE"
INV_MISSING_EXECUTION: Final[str] = "INV_MISSING_EXECUTION"
INV_EMPTY_CRITIQUE: Final[str] = "INV_EMPTY_CRITIQUE"
INV_INVALID_TRANSITION: Final[str] = "INV_INVALID_TRANSITION"


# ============================================================
# ROUTING DECISION FIELD NAMES
# ============================================================

FIELD_SELECTED_SOURCE: Final[str] = "selected_source"
FIELD_STRICT_PARSE_VALID: Final[str] = "strict_parse_valid"
FIELD_RECOVERY_PARSE_VALID: Final[str] = "recovery_parse_valid"
FIELD_STRICT_STRUCTURALLY_VALID: Final[str] = "strict_structurally_valid"
FIELD_RECOVERY_STRUCTURALLY_VALID: Final[str] = "recovery_structurally_valid"
FIELD_RECOVERY_USED: Final[str] = "recovery_used"
FIELD_DIVERGENCE_DETECTED: Final[str] = "divergence_detected"
FIELD_STRUCTURAL_ERRORS: Final[str] = "structural_errors"


# ============================================================
# AGGREGATION SUMMARY FIELD NAMES
# ============================================================

FIELD_PRIMARY: Final[str] = "primary"
FIELD_ALL: Final[str] = "all"
FIELD_PRIMARY_ID: Final[str] = "primary_id"
FIELD_ORACLE_CORRECT: Final[str] = "oracle_correct"
FIELD_REASONING_TRUTH: Final[str] = "reasoning_truth"
FIELD_CANONICAL_DIMS: Final[str] = "canonical_dims"
FIELD_CLASSIFY_EVENT_ID: Final[str] = "classify_event_id"
FIELD_RESULT: Final[str] = "result"


# ============================================================
# GENERATION CONTRACT FIELDS
# ============================================================

GEN_FIELD_ROOT_CAUSE: Final[str] = "root_cause"
GEN_FIELD_FIX_STRATEGY: Final[str] = "fix_strategy"
GEN_FIELD_FILES: Final[str] = "files"

GENERATION_CONTRACT: Final[FrozenSet[str]] = frozenset({
    GEN_FIELD_ROOT_CAUSE,
    GEN_FIELD_FIX_STRATEGY,
    GEN_FIELD_FILES,
})


# ============================================================
# CASE DICT FIELD NAMES
# ============================================================

CASE_FIELD_ID: Final[str] = "id"
CASE_FIELD_LOGICAL_FILE_KEYS: Final[str] = "logical_file_keys"
CASE_FIELD_TEMPLATE: Final[str] = "template"
CASE_FIELD_SWEBENCH: Final[str] = "_swebench"

TEMPLATE_SWEBENCH_REAL_WORLD: Final[str] = "swebench_real_world"


# ============================================================
# ARTIFACT VALUES
# ============================================================

ARTIFACT_ID_NONE: Final[str] = "no_artifact"
STATUS_GENERATION_CONTRACT_VIOLATION: Final[str] = "GENERATION_CONTRACT_VIOLATION"


# ============================================================
# AST RESULT VALUES
# ============================================================

AST_STATUS_NOT_MEASURABLE: Final[str] = "not_measurable"
AST_REASON_RECON_FAILED: Final[str] = "reconstruction_failed"


# ============================================================
# RECONSTRUCTION STATUS
# ============================================================

RECON_SUCCESS: Final[str] = "SUCCESS"
RECON_MISSING_FILES: Final[str] = "RECON_MISSING_FILES"


# ============================================================
# NORMALIZED REASONING ATTRIBUTE NAMES
# ============================================================

ATTR_RAW_ROOT_CAUSE: Final[str] = "raw_root_cause"
ATTR_RAW_FIX_STRATEGY: Final[str] = "raw_fix_strategy"
ATTR_EXECUTION_EQUIVALENT: Final[str] = "execution_equivalent"
ATTR_FILES_DICT: Final[str] = "files_dict"
ATTR_PARSE_VALID: Final[str] = "parse_valid"
ATTR_FULL_JSON: Final[str] = "full_json"


# ============================================================
# EFFECT LOG FIELD NAMES
# ============================================================

EFFECT_TYPE_LLM: Final[str] = "llm"
EFFECT_TYPE_SUBPROCESS: Final[str] = "subprocess"
EFFECT_TYPE_FILE_IO: Final[str] = "file_io"

EFFECT_STATUS_SUCCESS: Final[str] = "success"
EFFECT_STATUS_ERROR: Final[str] = "error"

EFFECT_FIELD_NODE: Final[str] = "node"
EFFECT_FIELD_CALL_TYPE: Final[str] = "call_type"
EFFECT_FIELD_DURATION_MS: Final[str] = "duration_ms"
EFFECT_FIELD_STATUS: Final[str] = "status"
EFFECT_FIELD_ERROR_TYPE: Final[str] = "error_type"
EFFECT_FIELD_METADATA: Final[str] = "metadata"


# ============================================================
# LOG NODE VALUES
# ============================================================

LOG_STATUS_WRITTEN: Final[str] = "written"
LOG_STATUS_SKIPPED: Final[str] = "skipped_no_output_path"


# ============================================================
# NODE REGISTRY IDS
# ============================================================

NODE_ID_PROMPT_BUILD: Final[str] = "prompt_build"
NODE_ID_PARSE: Final[str] = "parse"
NODE_ID_ROUTE: Final[str] = "route"
NODE_ID_NORMALIZE: Final[str] = "normalize"
NODE_ID_RECONSTRUCT: Final[str] = "reconstruct"
NODE_ID_AST_VERIFY: Final[str] = "ast_verify"
NODE_ID_SPEC_ORACLE: Final[str] = "spec_oracle"
NODE_ID_GENERATE: Final[str] = "generate"
NODE_ID_EXECUTE: Final[str] = "execute"
NODE_ID_LOG: Final[str] = "log"
NODE_ID_METRICS: Final[str] = "metrics"
NODE_ID_ASSEMBLE: Final[str] = "assemble"
NODE_ID_ORACLE_INLINE: Final[str] = "oracle.inline"
NODE_ID_ORACLE_AGGREGATION: Final[str] = "oracle_aggregation"
NODE_ID_CLASSIFIER_REASONING: Final[str] = "classifier.reasoning"
NODE_ID_CLASSIFIER_AGGREGATION: Final[str] = "classifier_aggregation"


# ============================================================
# EXEC RESULT SCHEMA KEYS
# ============================================================

EXEC_KEY_PASS: Final[str] = "pass"
EXEC_KEY_SCORE: Final[str] = "score"
EXEC_KEY_REASONS: Final[str] = "reasons"
EXEC_KEY_EXECUTION_CATEGORY: Final[str] = "execution_category"
EXEC_KEY_FAILURE_TYPE: Final[str] = "failure_type"
EXEC_KEY_EXECUTION: Final[str] = "execution"
EXEC_KEY_STATUS: Final[str] = "status"
EXEC_KEY_RAN: Final[str] = "ran"
EXEC_STATUS_NOT_EXECUTED: Final[str] = "not_executed"


# ============================================================
# DDC TRAP SEPARATOR
# ============================================================

DDC_TRAP_SEPARATOR: Final[str] = "_trap_"


# ============================================================
# RECONSTRUCTION FILE MARKERS
# ============================================================

FILE_MARKER_MODIFIED: Final[str] = "MODIFIED"
FILE_MARKER_UNCHANGED: Final[str] = "UNCHANGED"


# ============================================================
# NODE OUTCOME VALUES
# ============================================================

OUTCOME_SUCCESS: Final[str] = "success"
OUTCOME_ERROR: Final[str] = "error"
OUTCOME_SKIPPED: Final[str] = "skipped"
