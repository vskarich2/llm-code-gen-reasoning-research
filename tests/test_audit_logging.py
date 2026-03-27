"""Tests for audit logging fields in run.jsonl output.

Verifies that run.jsonl records contain the required audit fields.
Redundant fields (raw_model_output, classifier_prompt, classifier_raw_output)
have been removed — those are in calls/*.json now.
"""

import json
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# The required audit fields in run.jsonl (after redundancy removal)
REQUIRED_AUDIT_FIELDS = [
    "case_id",
    "condition",
    "parsed_reasoning",
    "parse_error",
    "parse_category",
    "recovery_method",
    "classifier_verdict",
    "classifier_failure_type",
    "classifier_parse_error",
    "eval_model_intended",
    "eval_model_actual",
    "code_present",
    "code_empty_reason",
    "code_source",
    "case_validity",
    "failure_source",
    "failure_source_detail",
    "recovery_applied",
    "recovery_types",
    "content_normalized",
    "data_lineage",
]

# Fields that are legitimately None for clean cases
ALLOWED_NONE_FIELDS = {
    "parse_error",
    "classifier_parse_error",
    "recovery_method",
    "code_empty_reason",
}


class TestAuditFieldCompleteness:
    """Verify audit fields exist in logged records."""

    def _run_mock_pipeline_and_get_record(
        self, tmp_path, reasoning="The bug is aliasing", parse_error=None
    ):
        """Run a mock case through the full pipeline and return the log record."""
        from execution import RunLogger

        log_path = tmp_path / "run.jsonl"
        logger = RunLogger(log_path, model="test-model", run_id="test-run")

        ev = {
            "pass": True,
            "score": 1.0,
            "reasons": [],
            "failure_modes": [],
            "execution": {"status": "passed", "ran": True},
            "identified_correct_issue": True,
            "alignment": {"category": "true_success"},
            "num_attempts": 1,
            "reasoning_correct": True,
            "failure_type": "ALIASING",
            "classify_raw": "YES ; ALIASING",
            "classify_parse_error": None,
            "classifier_prompt": "You are evaluating...",
            "eval_model_intended": "intended-model",
            "eval_model_actual": "actual-model",
            "parse_category": "CLEAN",
            "code_present": True,
            "code_empty_reason": None,
            "code_source": "reconstruction",
            "case_validity": "valid",
            "failure_source": "SUCCESS",
            "failure_source_detail": "none",
            "recovery_applied": False,
            "recovery_types": [],
            "content_normalized": False,
        }

        parsed = {
            "reasoning": reasoning,
            "code": "def create_config(): return dict(DEFAULTS)",
            "parse_error": parse_error,
            "_raw_fallback": False,
            "data_lineage": ["raw_output_received"],
        }

        logger.write(
            "test_case",
            "baseline",
            "test-model",
            "Fix the bug...",
            "raw model output here",
            parsed,
            ev,
        )

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1, f"Expected 1 log line, got {len(lines)}"
        return json.loads(lines[0])

    def test_audit_block_exists(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert "audit" in record, "Log record missing 'audit' block"

    def test_all_required_fields_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["audit"]
        missing = [f for f in REQUIRED_AUDIT_FIELDS if f not in audit]
        assert missing == [], (
            f"Missing audit fields: {missing}. " f"Present: {sorted(audit.keys())}"
        )

    def test_field_count(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["audit"]
        assert len(audit) == len(REQUIRED_AUDIT_FIELDS), (
            f"Expected {len(REQUIRED_AUDIT_FIELDS)} audit fields, got {len(audit)}. "
            f"Fields: {sorted(audit.keys())}"
        )

    def test_non_none_fields_populated(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["audit"]
        must_be_populated = set(REQUIRED_AUDIT_FIELDS) - ALLOWED_NONE_FIELDS
        none_but_shouldnt_be = [f for f in must_be_populated if audit.get(f) is None]
        assert (
            none_but_shouldnt_be == []
        ), f"Fields that should be populated but are None: {none_but_shouldnt_be}"

    def test_case_id_matches(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["case_id"] == "test_case"

    def test_condition_matches(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["condition"] == "baseline"

    def test_parsed_reasoning_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["parsed_reasoning"] == "The bug is aliasing"

    def test_parse_category_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["parse_category"] == "CLEAN"

    def test_classifier_verdict_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["classifier_verdict"] is True

    def test_eval_model_intended_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["eval_model_intended"] == "intended-model"

    def test_eval_model_actual_present(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["eval_model_actual"] == "actual-model"

    def test_recovery_method_none_for_clean(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        assert record["audit"]["recovery_method"] is None

    def test_recovery_method_set_for_lenient(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(
            tmp_path,
            reasoning="recovered reasoning",
            parse_error="lenient-json: extracted from malformed JSON",
        )
        assert record["audit"]["recovery_method"] == "partial_json"

    def test_gated_case_has_audit_fields(self, tmp_path):
        from execution import RunLogger

        log_path = tmp_path / "run.jsonl"
        logger = RunLogger(log_path, model="test-model", run_id="test-run")

        ev = {
            "pass": False,
            "score": 0.0,
            "reasons": [],
            "failure_modes": [],
            "execution": {"status": "error", "ran": False},
            "identified_correct_issue": False,
            "alignment": {"category": "unclassified"},
            "num_attempts": 1,
            "reasoning_correct": None,
            "failure_type": None,
            "classify_raw": None,
            "classify_parse_error": "GATED:REASONING_LOST",
            "classifier_prompt": None,
            "eval_model_intended": None,
            "eval_model_actual": None,
            "parse_category": "REASONING_LOST",
            "code_present": False,
            "code_empty_reason": "parse_failure",
            "code_source": "unknown",
            "case_validity": "invalid",
            "failure_source": "PARSE_FAILURE",
            "failure_source_detail": "raw_fallback",
            "recovery_applied": False,
            "recovery_types": [],
            "content_normalized": False,
        }

        parsed = {
            "reasoning": "",
            "code": "def f(): pass",
            "parse_error": "extraction_error: NO_JSON",
            "_raw_fallback": False,
            "data_lineage": ["raw_output_received"],
        }

        logger.write("gated_case", "baseline", "test-model", "prompt", "raw output", parsed, ev)

        record = json.loads(log_path.read_text().strip())
        audit = record["audit"]

        missing = [f for f in REQUIRED_AUDIT_FIELDS if f not in audit]
        assert missing == [], f"Gated case missing audit fields: {missing}"
        assert audit["parse_category"] == "REASONING_LOST"
        assert audit["classifier_verdict"] is None

    def test_audit_fields_are_json_serializable(self, tmp_path):
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit_json = json.dumps(record["audit"], default=str)
        assert len(audit_json) > 0

    def test_no_redundant_raw_fields(self, tmp_path):
        """raw_model_output, classifier_prompt, classifier_raw_output
        must NOT be in audit — they live in calls/*.json now."""
        record = self._run_mock_pipeline_and_get_record(tmp_path)
        audit = record["audit"]
        assert "raw_model_output" not in audit
        assert "classifier_prompt" not in audit
        assert "classifier_raw_output" not in audit
