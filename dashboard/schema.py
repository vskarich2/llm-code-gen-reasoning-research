"""Field registry — single source of truth for all case_data fields.

Every field used anywhere in the dashboard MUST be defined here.
No field names hard-coded outside this file.
"""

# Source fields: extracted directly from WAL events or case metadata.
# key = column name in DataFrame
# source = dot-path into event dict (or "cases.X" for case metadata)
# type = Python type string for documentation
# required = if True, missing value raises error during loading

FIELD_REGISTRY = {
    # ── IDENTIFIERS ──
    "run_id": {
        "source": "run.run_id",
        "type": "str",
        "required": False,
    },
    "model": {
        "source": "model",
        "type": "str",
        "required": True,
    },
    "condition": {
        "source": "condition",
        "type": "str",
        "required": True,
    },
    "case_id": {
        "source": "case_id",
        "type": "str",
        "required": True,
    },
    "family": {
        "source": "cases.family",
        "type": "str",
        "required": False,
    },
    "difficulty": {
        "source": "cases.difficulty",
        "type": "str",
        "required": False,
    },
    "trial_idx": {
        "source": "trial",
        "type": "int",
        "required": True,
    },
    "attempt_idx": {
        "source": "attempt",
        "type": "int",
        "required": True,
    },
    "work_id": {
        "source": "work_id",
        "type": "str",
        "required": True,
    },
    "instance_id": {
        "source": "instance_id",
        "type": "str",
        "required": True,
    },

    # ── EXECUTION ──
    "exec_pass": {
        "source": "payload.pass",
        "type": "bool",
        "required": True,
    },
    "score": {
        "source": "payload.score",
        "type": "float",
        "required": False,
    },
    "tests_passed": {
        "source": "execution.tests_passed",
        "type": "int",
        "required": False,
    },
    "tests_total": {
        "source": "execution.tests_run",
        "type": "int",
        "required": False,
    },
    "runtime_ms": {
        "source": "execution.runtime_ms",
        "type": "int",
        "required": False,
    },
    "exec_category": {
        "source": "payload.execution_category",
        "type": "str",
        "required": False,
    },

    # ── REASONING ──
    "reasoning_correct": {
        "source": "reasoning.reasoning_correct",
        "type": "bool",
        "required": False,
    },
    "mechanism_label": {
        "source": "reasoning.failure_type",
        "type": "str",
        "required": False,
        # INVARIANT: failure_type lives ONLY in reasoning section.
        # It is consumed from top-level by logging_core into reasoning.
        # extra.failure_type is always None — do NOT read from extra.
    },
    "confidence": {
        "source": "reasoning.confidence",
        "type": "str",
        "required": False,
    },
    "mechanism_dim": {
        "source": "payload.mechanism_identified_dim",
        "type": "str",
        "required": False,
    },
    "commitments_dim": {
        "source": "payload.commitments_extracted_dim",
        "type": "str",
        "required": False,
    },
    "satisfied_dim": {
        "source": "payload.commitments_satisfied_dim",
        "type": "str",
        "required": False,
    },
    "alignment_dim": {
        "source": "payload.reasoning_code_alignment_dim",
        "type": "str",
        "required": False,
    },

    # ── CODE & EXECUTION DETAIL ──
    "_extracted_code": {
        "source": "payload._extracted_code",
        "type": "str",
        "required": False,
        "fallback_source": "extra._extracted_code",
    },
    "reconstruction_status": {
        "source": "payload.reconstruction_status",
        "type": "str",
        "required": False,
        "fallback_source": "extra.reconstruction_status",
    },
    "execution_trace": {
        "source": "payload.execution_trace",
        "type": "list",
        "required": False,
        "fallback_source": "extra.execution_trace",
    },
    "exec_reasons": {
        "source": "payload.reasons",
        "type": "list",
        "required": False,
        "fallback_source": "extra.reasons",
    },
    "functions_detected": {
        "source": "payload.functions_detected",
        "type": "list",
        "required": False,
        "fallback_source": "extra.functions_detected",
    },
    "functions_called": {
        "source": "payload.functions_called",
        "type": "list",
        "required": False,
        "fallback_source": "extra.functions_called",
    },
    "merge_conflicts": {
        "source": "payload.merge_conflicts",
        "type": "list",
        "required": False,
        "fallback_source": "extra.merge_conflicts",
    },

    # ── PARSE ──
    "parse_status": {
        "source": "payload.v2_artifact.parse_status",
        "type": "str",
        "required": False,
        "fallback_source": "v2_artifact.parse_status",
    },
    "v2_parse_tiers": {
        "source": "payload.v2_parse_tiers",
        "type": "dict",
        "required": False,
        "fallback_source": "extra.v2_parse_tiers",
    },
    "classify_v2_parse_error": {
        "source": "payload.classify_v2_parse_error",
        "type": "str",
        "required": False,
        "fallback_source": "extra.classify_v2_parse_error",
    },

    # ── RECONSTRUCTION ──
    "recon_status": {
        "source": "extra.reconstruction.recon_status",
        "type": "str",
        "required": False,
    },
    "reconstruction_mode": {
        "source": "extra.reconstruction.reconstruction_mode",
        "type": "str",
        "required": False,
    },
    "parsing_mode": {
        "source": "extra.reconstruction.parsing_mode",
        "type": "str",
        "required": False,
    },
    "strict_parse_valid": {
        "source": "extra.reconstruction.strict_parse_valid",
        "type": "bool",
        "required": False,
    },
    "recovery_parse_valid": {
        "source": "extra.reconstruction.recovery_parse_valid",
        "type": "bool",
        "required": False,
    },
    "strict_structurally_valid": {
        "source": "extra.reconstruction.strict_structurally_valid",
        "type": "bool",
        "required": False,
    },
    "recovery_structurally_valid": {
        "source": "extra.reconstruction.recovery_structurally_valid",
        "type": "bool",
        "required": False,
    },
    "recovery_used": {
        "source": "extra.reconstruction.recovery_used",
        "type": "bool",
        "required": False,
    },
    "divergence_detected": {
        "source": "extra.reconstruction.divergence_detected",
        "type": "bool",
        "required": False,
    },
    "execution_eligible": {
        "source": "extra.reconstruction.execution_eligible",
        "type": "bool",
        "required": False,
    },
    "files_changed": {
        "source": "extra.reconstruction.files_changed",
        "type": "list",
        "required": False,
    },
    "files_missing": {
        "source": "extra.reconstruction.files_missing",
        "type": "list",
        "required": False,
    },
    "files_extra": {
        "source": "extra.reconstruction.files_extra",
        "type": "list",
        "required": False,
    },
    "files_total": {
        "source": "extra.reconstruction.files_total",
        "type": "int",
        "required": False,
    },
    "syntax_errors": {
        "source": "extra.reconstruction.syntax_errors",
        "type": "dict",
        "required": False,
    },
    "format_violation": {
        "source": "extra.reconstruction.format_violation",
        "type": "bool",
        "required": False,
    },
    "content_normalized": {
        "source": "extra.reconstruction.content_normalized",
        "type": "bool",
        "required": False,
    },
    "normalization_log": {
        "source": "extra.reconstruction.normalization_log",
        "type": "list",
        "required": False,
    },
    "recovery_applied": {
        "source": "extra.reconstruction.recovery_applied",
        "type": "bool",
        "required": False,
    },
    "recovery_types": {
        "source": "extra.reconstruction.recovery_types",
        "type": "list",
        "required": False,
    },
    "structural_errors": {
        "source": "extra.reconstruction.structural_errors",
        "type": "list",
        "required": False,
    },
    "semantic_diagnostics": {
        "source": "extra.reconstruction.semantic_diagnostics",
        "type": "dict",
        "required": False,
    },

    # ── CLASSIFIER METADATA ──
    "classifier_schema_variant": {
        "source": "extra.classifier_schema_variant",
        "type": "str",
        "required": False,
    },
    "classifier_prompt_variant": {
        "source": "extra.classifier_prompt_variant",
        "type": "str",
        "required": False,
    },

    # ── RETRY ──
    "retry_passed_at": {
        "source": "payload.retry_passed_at",
        "type": "int",
        "required": False,
    },

    # ── TIMESTAMPS ──
    "timestamp": {
        "source": "timestamp",
        "type": "str",
        "required": False,
    },

    # ── V3 EVALUATION (3-axis model) ──
    "outcome_class": {
        "source": "payload.evaluation.outcome_class",
        "type": "str",
        "required": False,
    },
    "serialization_success": {
        "source": "payload.evaluation.serialization_success",
        "type": "bool",
        "required": False,
    },
    "execution_success": {
        "source": "payload.evaluation.execution_success",
        "type": "bool",
        "required": False,
    },
    "reasoning_sufficient": {
        "source": "payload.evaluation.reasoning_sufficient",
        "type": "bool",
        "required": False,
    },
    "LEG_field": {
        "source": "payload.evaluation.LEG",
        "type": "bool",
        "required": False,
    },
    "LEG_subtype": {
        "source": "payload.evaluation.LEG_subtype",
        "type": "str",
        "required": False,
    },

    # ── V3 AST EVAL ──
    "ast_status": {
        "source": "payload.ast_eval.status",
        "type": "str",
        "required": False,
    },
    "ast_correct": {
        "source": "payload.ast_eval.ast_correct",
        "type": "bool",
        "required": False,
    },
    "ast_score": {
        "source": "payload.ast_eval.ast_score",
        "type": "float",
        "required": False,
    },

    # ── V3 CLASSIFICATION ──
    "classifier_mechanism": {
        "source": "payload.classification.mechanism_identified",
        "type": "str",
        "required": False,
    },
    "classifier_commitments": {
        "source": "payload.classification.commitments_satisfied",
        "type": "str",
        "required": False,
    },
    "classifier_alignment": {
        "source": "payload.classification.reasoning_code_alignment",
        "type": "str",
        "required": False,
    },
    "classifier_ran": {
        "source": "payload.classification.classifier_ran",
        "type": "bool",
        "required": False,
    },
}


def get_source_fields():
    """Return list of (column_name, source_path) for event extraction."""
    return [
        (name, spec["source"])
        for name, spec in FIELD_REGISTRY.items()
        if not spec["source"].startswith("cases.")
    ]


def get_case_fields():
    """Return list of (column_name, case_key) for case metadata join."""
    return [
        (name, spec["source"].split(".", 1)[1])
        for name, spec in FIELD_REGISTRY.items()
        if spec["source"].startswith("cases.")
    ]


def get_required_fields():
    """Return field names that must be present (non-null) in every row."""
    return [
        name for name, spec in FIELD_REGISTRY.items()
        if spec.get("required", False)
    ]
