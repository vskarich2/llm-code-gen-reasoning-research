"""Tests for reasoning_evaluator_audit logging: all 21 fields present in JSONL output.

Verifies Go/No-Go item 3: complete reasoning_evaluator_audit instrumentation.
"""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# The 21 required reasoning_evaluator_audit fields from plan v6 Section 8.3
REQUIRED_AUDIT_FIELDS = [
    "experiment_id",
    "case_id",
    "condition",
    "raw_model_output",
    "parsed_reasoning",
    "enriched_reasoning",
    "normalized_representation",
    "extraction_method",
    "extraction_failed",
    "extraction_e1_correct",
    "parse_error",
    "parse_category",
    "recovery_method",
    "classifier_prompt",
    "classifier_raw_output",
    "classifier_verdict",
    "classifier_failure_type",
    "classifier_parse_error",
    "eval_model_intended",
    "eval_model_actual",
    "semantic_elements",
]

# Fields that are allowed to be None in current implementation.
# Two categories:
# 1. Phase 1 / Fix C fields: not yet implemented
# 2. Legitimately None for CLEAN cases: no error means None
ALLOWED_NONE_FIELDS = {
    # Phase 1 / Fix C (not yet implemented)
    "experiment_id",
    "enriched_reasoning",
    "normalized_representation",
    "extraction_method",
    "extraction_failed",
    "extraction_e1_correct",
    "semantic_elements",
    # Legitimately None for CLEAN cases (no error = no value)
    "parse_error",              # None when parsing succeeded
    "classifier_parse_error",   # None when classifier output parsed OK
    "recovery_method",          # None when no recovery was needed
    "classifier_prompt",        # None when parse gate fired (no classifier call)
}


class TestAuditFieldCompleteness:
    """Verify all 21 reasoning_evaluator_audit fields exist in logged records."""

    def _run_mock_pipeline_and_get_record(self, tmp_path,
                                           reasoning="The bug is aliasing",
                                           parse_error=None):
        """Run a mock case through the full pipeline and return the log record."""
        from execution import RunLogger

        log_path = tmp_path / "run.jsonl"
        prompts_path = tmp_path / "run_prompts.jsonl"
        responses_path = tmp_path / "run_responses.jsonl"

        logger = RunLogger(log_path, prompts_path, responses_path,
                           model="test-model", run_id="test-run")

        # Mock eval result as produced by evaluate_output
        ev = {
            "pass": True,
            "score": 1.0,
            "reasons": [],
            "failure_modes": [],
            "execution": {"status": "passed", "ran": True},
            "identified_correct_issue": True,
            "alignment": {"category": "true_success"},
            "num_attempts": 1,
            # Fields from llm_classify (Fix D + Fix E)
            "reasoning_correct": True,
            "failure_type": "ALIASING",
            "classify_raw": "YES ; ALIASING",
            "classify_parse_error": None,
            "classifier_prompt": "You are evaluating...",
            "eval_model_intended": "intended-model",
            "eval_model_actual": "actual-model",
            "parse_category": "CLEAN",
        }

        parsed = {
            "reasoning": reasoning,
            "code": "def create_config(): return dict(DEFAULTS)",
            "parse_error": parse_error,
            "_raw_fallback": False,
        }

        logger.write("test_case", "baseline", "test-model",
                      "Fix the bug...", "raw model output here", parsed, ev)

        # Read back the log record
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1, f"Expected 1 log line, got {len(lines)}"
        record = json.loads(lines[0])
        return record

    def test_audit_block_exists(self, tmp_path):
        """The 'reasoning_evaluator_audit' key must exist in the log record."""
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert "reasoning_evaluator_audit" in record, "Log record missing 'reasoning_evaluator_audit' block"

    def test_all_21_fields_present(self, tmp_path):
        """Every one of the 21 required reasoning_evaluator_audit fields must exist."""
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["reasoning_evaluator_audit"]

        missing = [f for f in REQUIRED_AUDIT_FIELDS if f not in audit]
        assert missing == [], (
            f"Missing reasoning_evaluator_audit fields: {missing}. "
            f"Present fields: {sorted(audit.keys())}. "
            f"Required: {sorted(REQUIRED_AUDIT_FIELDS)}"
        )

    def test_field_count_is_31(self, tmp_path):
        """Audit block must have exactly 31 fields (21 original + 10 Phase 1)."""
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["reasoning_evaluator_audit"]
        assert len(audit) == 31, (
            f"Expected 31 reasoning_evaluator_audit fields, got {len(audit)}. "
            f"Fields: {sorted(audit.keys())}"
        )

    def test_non_none_fields_populated(self, tmp_path):
        """Fields that should be populated in the current implementation
        must not be None."""
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["reasoning_evaluator_audit"]

        must_be_populated = set(REQUIRED_AUDIT_FIELDS) - ALLOWED_NONE_FIELDS
        none_but_shouldnt_be = [
            f for f in must_be_populated
            if audit.get(f) is None
        ]
        assert none_but_shouldnt_be == [], (
            f"Fields that should be populated but are None: {none_but_shouldnt_be}"
        )

    def test_case_id_matches(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["case_id"] == "test_case"

    def test_condition_matches(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["condition"] == "baseline"

    def test_raw_model_output_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["raw_model_output"] == "raw model output here"

    def test_parsed_reasoning_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["parsed_reasoning"] == "The bug is aliasing"

    def test_parse_category_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["parse_category"] == "CLEAN"

    def test_classifier_prompt_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["classifier_prompt"] == "You are evaluating..."

    def test_classifier_raw_output_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["classifier_raw_output"] == "YES ; ALIASING"

    def test_classifier_verdict_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["classifier_verdict"] is True

    def test_eval_model_intended_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["eval_model_intended"] == "intended-model"

    def test_eval_model_actual_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["eval_model_actual"] == "actual-model"

    def test_recovery_method_none_for_clean(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["reasoning_evaluator_audit"]["recovery_method"] is None

    def test_recovery_method_set_for_lenient(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(
            tmp_path,
            reasoning="recovered reasoning",
            parse_error="lenient-json: extracted from malformed JSON",
        )
        assert record["reasoning_evaluator_audit"]["recovery_method"] == "partial_json"

    def test_gated_case_has_audit_fields(self, tmp_path):
        """Even when parse gate fires, reasoning_evaluator_audit fields must be present."""
        from execution import RunLogger

        log_path = tmp_path / "run.jsonl"
        logger = RunLogger(log_path, tmp_path / "p.jsonl", tmp_path / "r.jsonl",
                           model="test-model", run_id="test-run")

        ev = {
            "pass": False, "score": 0.0, "reasons": [], "failure_modes": [],
            "execution": {"status": "error", "ran": False},
            "identified_correct_issue": False,
            "alignment": {"category": "unclassified"},
            "num_attempts": 1,
            # Gated result from llm_classify
            "reasoning_correct": None,
            "failure_type": None,
            "classify_raw": None,
            "classify_parse_error": "GATED:REASONING_LOST",
            "classifier_prompt": None,
            "eval_model_intended": None,
            "eval_model_actual": None,
            "parse_category": "REASONING_LOST",
        }

        parsed = {
            "reasoning": "",
            "code": "def f(): pass",
            "parse_error": "extraction_error: NO_JSON",
            "_raw_fallback": False,
        }

        logger.write("gated_case", "baseline", "test-model",
                      "prompt", "raw output", parsed, ev)

        record = json.loads(log_path.read_text().strip())
        audit = record["reasoning_evaluator_audit"]

        # All 21 fields must still exist
        missing = [f for f in REQUIRED_AUDIT_FIELDS if f not in audit]
        assert missing == [], f"Gated case missing reasoning_evaluator_audit fields: {missing}"
        assert audit["parse_category"] == "REASONING_LOST"
        assert audit["classifier_verdict"] is None

    def test_audit_fields_are_json_serializable(self, tmp_path):
        """All reasoning_evaluator_audit fields must serialize to JSON without error."""
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        # If we got here, json.dumps already worked in write().
        # Double-check by re-serializing the reasoning_evaluator_audit block.
        audit_json = json.dumps(record["reasoning_evaluator_audit"], default=str)
        assert len(audit_json) > 0
