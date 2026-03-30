"""Unit tests for all v2 modules: contracts, mapping, parser, reasoning, evaluator, metrics."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from contracts_v2 import (
    V2_BASELINE_REQUIRED, V2_LEG_REQUIRED, V2_LEAN_REQUIRED,
    validate_generation_fields, CONDITION_TO_SCHEMA,
)
from mapping_v2 import get_canonical_family, is_mapped, FAILURE_MODE_TO_CANONICAL
from parser_v2 import parse_generation_v2, ParsedGenerationV2
from reasoning_v2 import normalize_commitments, normalize_generation_v2, NormalizedReasoningArtifactV2
from evaluator_v2 import parse_classifier_v2_output, ClassifierResultV2
from metrics_v2 import derive_v2_signals, V2Signals


# ============================================================
# CONTRACTS
# ============================================================


def test_baseline_required_fields():
    assert V2_BASELINE_REQUIRED == frozenset({"root_cause", "fix_strategy", "files"})


def test_leg_required_fields():
    assert V2_LEG_REQUIRED == frozenset({"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"})


def test_lean_required_fields():
    assert V2_LEAN_REQUIRED == V2_LEG_REQUIRED


def test_validate_valid_baseline():
    status, errors = validate_generation_fields(
        {"root_cause": "a" * 20, "fix_strategy": "b" * 20, "files": {"a.py": "pass"}},
        "baseline_v2",
    )
    assert status == "valid"
    assert errors == []


def test_validate_missing_root_cause():
    status, errors = validate_generation_fields(
        {"fix_strategy": "b" * 20, "files": {"a.py": "pass"}},
        "baseline_v2",
    )
    assert status == "invalid"
    assert any("root_cause" in e for e in errors)


def test_validate_lean_safe_risk_check():
    status, errors = validate_generation_fields(
        {"root_cause": "a" * 20, "code_commitments": ["x must y"], "fix_strategy": "b" * 20,
         "risk_check": "SAFE", "files": {"a.py": "pass"}},
        "lean_v2",
    )
    assert status == "valid"


# ============================================================
# MAPPING
# ============================================================


def test_mapped_family():
    assert get_canonical_family({"failure_mode": "ALIASING"}) == "ALIASING"
    assert get_canonical_family({"failure_mode": "STALE_CACHE"}) == "STALE_CACHE"


def test_unmapped_family():
    assert get_canonical_family({"failure_mode": "RACE_CONDITION"}) is None
    assert not is_mapped({"failure_mode": "RACE_CONDITION"})


def test_all_mapped_produce_canonical():
    for fm, canonical in FAILURE_MODE_TO_CANONICAL.items():
        assert get_canonical_family({"failure_mode": fm}) == canonical


# ============================================================
# PARSER
# ============================================================


def test_parse_valid_leg_v2():
    raw = json.dumps({
        "root_cause": "create_config returns DEFAULTS by reference",
        "code_commitments": ["create_config must return copy"],
        "fix_strategy": "use DEFAULTS.copy() to return independent dict",
        "risk_check": "safe because flat dict",
        "files": {"config.py": "pass"},
    })
    result = parse_generation_v2(raw, "leg_reduction_v2")
    assert result.parse_status == "success"
    assert result.schema_variant == "leg_v2"
    assert result.full_json["code_commitments"] == ["create_config must return copy"]
    assert result.files_dict == {"config.py": "pass"}


def test_parse_valid_baseline_v2_no_commitments():
    raw = json.dumps({
        "root_cause": "create_config returns DEFAULTS by reference",
        "fix_strategy": "use DEFAULTS.copy() to return independent dict",
        "files": {"config.py": "pass"},
    })
    result = parse_generation_v2(raw, "baseline_v2")
    assert result.parse_status == "success"
    assert "code_commitments" not in result.full_json


def test_parse_malformed_json():
    result = parse_generation_v2("{bad json here", "leg_reduction_v2")
    assert result.parse_status == "failed"
    assert result.full_json is None


def test_parse_fenced_json():
    raw = '```json\n{"root_cause": "' + "x" * 20 + '", "fix_strategy": "' + "y" * 20 + '", "files": {"a.py": "pass"}}\n```'
    result = parse_generation_v2(raw, "baseline_v2")
    assert result.parse_status == "success"


def test_parse_empty_response():
    result = parse_generation_v2("", "baseline_v2")
    assert result.parse_status == "failed"
    assert result.parse_error == "empty_response"


def test_parse_missing_files():
    raw = json.dumps({"root_cause": "x" * 20, "fix_strategy": "y" * 20})
    result = parse_generation_v2(raw, "baseline_v2")
    assert result.parse_status == "invalid"
    assert any("files" in e for e in result.validation_errors)


def test_parse_extra_fields_preserved():
    raw = json.dumps({
        "root_cause": "x" * 20, "fix_strategy": "y" * 20,
        "files": {"a.py": "pass"}, "extra_field": "preserved",
    })
    result = parse_generation_v2(raw, "baseline_v2")
    assert result.parse_status == "success"
    assert result.full_json["extra_field"] == "preserved"


# ============================================================
# REASONING NORMALIZATION
# ============================================================


def test_normalize_strip_dedup():
    result = normalize_commitments(["  x must y  ", "x must y", "z must w"])
    assert result == ["x must y", "z must w"]


def test_normalize_compound_split():
    notes = []
    result = normalize_commitments(
        ["create_config must return copy and DEFAULTS must not be mutated"],
        notes,
    )
    assert len(result) == 2
    assert "create_config must return copy" in result
    assert "DEFAULTS must not be mutated" in result
    assert any("split" in n for n in notes)


def test_normalize_preserve_vague():
    result = normalize_commitments(["fix shared state issue"])
    assert len(result) == 1
    assert "[unscoped]" in result[0]  # no "must" → scopeless


def test_normalize_scopeless_tagged():
    notes = []
    result = normalize_commitments(["fix the bug"], notes)
    assert result == ["[unscoped] fix the bug"]
    assert any("scope" in n for n in notes)


def test_normalize_string_to_list():
    notes = []
    result = normalize_commitments("single commitment must work", notes)
    assert len(result) == 1
    assert any("string to list" in n for n in notes)


def test_normalize_nonlist_returns_empty():
    notes = []
    result = normalize_commitments(42, notes)
    assert result == []


def test_normalize_generation_leg_v2():
    parsed = ParsedGenerationV2(
        parse_status="success", schema_variant="leg_v2",
        full_json={
            "root_cause": "create_config returns DEFAULTS",
            "code_commitments": ["create_config must return copy"],
            "fix_strategy": "use .copy()",
            "risk_check": "safe",
            "files": {"a.py": "pass"},
        },
        files_dict={"a.py": "pass"}, parse_error=None,
        raw_response_text="...",
    )
    case = {"failure_mode": "ALIASING"}
    artifact = normalize_generation_v2(parsed, case, "leg_reduction_v2")
    assert artifact.commitments_source == "explicit"
    assert artifact.commitment_count == 1
    assert artifact.canonical_family == "ALIASING"
    assert artifact.canonical_family_mapped is True


def test_normalize_generation_baseline_no_commitments():
    parsed = ParsedGenerationV2(
        parse_status="success", schema_variant="baseline_v2",
        full_json={
            "root_cause": "bug in create_config",
            "fix_strategy": "use copy",
            "files": {"a.py": "pass"},
        },
        files_dict={"a.py": "pass"}, parse_error=None,
        raw_response_text="...",
    )
    artifact = normalize_generation_v2(parsed, {"failure_mode": "ALIASING"}, "baseline_v2")
    assert artifact.commitments_source == "none"
    assert artifact.commitment_extractability_status == "absent"


def test_normalize_generation_baseline_spontaneous():
    parsed = ParsedGenerationV2(
        parse_status="success", schema_variant="baseline_v2",
        full_json={
            "root_cause": "bug",
            "fix_strategy": "fix",
            "code_commitments": ["create_config must return copy"],
            "files": {"a.py": "pass"},
        },
        files_dict={"a.py": "pass"}, parse_error=None,
        raw_response_text="...",
    )
    artifact = normalize_generation_v2(parsed, {"failure_mode": "ALIASING"}, "baseline_v2")
    assert artifact.commitments_source == "spontaneous"
    assert artifact.commitment_extractability_status == "present"


def test_normalize_generation_failed_parse():
    parsed = ParsedGenerationV2(
        parse_status="failed", schema_variant="leg_v2",
        full_json=None, files_dict=None,
        parse_error="no JSON", raw_response_text="just text",
    )
    artifact = normalize_generation_v2(parsed, {}, "leg_reduction_v2")
    assert artifact.parse_status == "failed"
    assert artifact.validation_status == "invalid"


# ============================================================
# EVALUATOR V2 — CLASSIFIER PARSER
# ============================================================


def test_parse_valid_classifier_v2():
    raw = "CORRECT;CORRECT;PARTIAL;CORRECT;HIDDEN_DEPENDENCY\nHIGH\nCounterfactual: if fixed\nEvidence: code shows\nJudgment: good fix"
    result = parse_classifier_v2_output(raw)
    assert result.parse_error is None
    assert result.mechanism_identified == "CORRECT"
    assert result.commitments_extracted == "CORRECT"
    assert result.commitments_satisfied == "PARTIAL"
    assert result.reasoning_code_alignment == "CORRECT"
    assert result.failure_type == "HIDDEN_DEPENDENCY"
    assert result.confidence == "HIGH"


def test_parse_classifier_wrong_field_count():
    raw = "CORRECT;CORRECT;PARTIAL;ALIASING\nHIGH\nC\nE\nJ"
    result = parse_classifier_v2_output(raw)
    assert result.parse_error is not None
    assert "4 fields" in result.parse_error or "expected 5" in result.parse_error


def test_parse_classifier_bad_dimension():
    raw = "CORRECT;MAYBE;PARTIAL;CORRECT;ALIASING\nHIGH\nC\nE\nJ"
    result = parse_classifier_v2_output(raw)
    assert result.parse_error is not None
    assert "MAYBE" in result.parse_error


def test_parse_classifier_debug_stripped():
    raw = "CORRECT;CORRECT;CORRECT;CORRECT;ALIASING\nHIGH\nCounterfactual: x\nEvidence: y\nJudgment: z\n---DEBUG---\nextra stuff"
    result = parse_classifier_v2_output(raw)
    assert result.parse_error is None


def test_parse_classifier_empty():
    result = parse_classifier_v2_output("")
    assert result.parse_error is not None


# ============================================================
# METRICS
# ============================================================


def test_signals_all_correct():
    signals = derive_v2_signals(
        {"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT",
         "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"},
        code_correct=True, commitments_source="explicit",
    )
    assert signals.mechanism_correct is True
    assert signals.commitments_valid is True
    assert signals.alignment_positive is True
    assert signals.v2_category == "interpretable_success"


def test_signals_mechanism_wrong():
    signals = derive_v2_signals(
        {"mechanism_identified": "WRONG", "commitments_extracted": "CORRECT",
         "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"},
        code_correct=True, commitments_source="explicit",
    )
    assert signals.mechanism_correct is False
    assert signals.v2_category == "lucky_fix_v2"


def test_signals_leg_v2():
    signals = derive_v2_signals(
        {"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT",
         "commitments_satisfied": "PARTIAL", "reasoning_code_alignment": "WRONG"},
        code_correct=False, commitments_source="explicit",
    )
    assert signals.mechanism_correct is True
    assert signals.commitments_valid is True
    assert signals.alignment_positive is False
    assert signals.v2_category == "LEG_v2"


def test_signals_uninterpretable_success():
    signals = derive_v2_signals(
        {"mechanism_identified": "CORRECT", "commitments_extracted": "WRONG",
         "commitments_satisfied": "WRONG", "reasoning_code_alignment": "CORRECT"},
        code_correct=True, commitments_source="none",
    )
    assert signals.v2_category == "uninterpretable_success"


def test_signals_full_failure():
    signals = derive_v2_signals(
        {"mechanism_identified": "WRONG", "commitments_extracted": "WRONG",
         "commitments_satisfied": "WRONG", "reasoning_code_alignment": "WRONG"},
        code_correct=False, commitments_source="explicit",
    )
    assert signals.v2_category == "full_failure_v2"


def test_signals_classifier_failure():
    signals = derive_v2_signals(
        {"mechanism_identified": None, "commitments_extracted": None,
         "commitments_satisfied": None, "reasoning_code_alignment": None},
        code_correct=True, commitments_source="explicit",
    )
    assert signals.v2_category == "classifier_failure_v2"


def test_signals_alignment_failure_pass():
    signals = derive_v2_signals(
        {"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT",
         "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "WRONG"},
        code_correct=True, commitments_source="explicit",
    )
    assert signals.v2_category == "alignment_failure_pass"


def test_legacy_compat_true_success():
    signals = derive_v2_signals(
        {"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT",
         "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"},
        code_correct=True, commitments_source="explicit",
    )
    assert signals.legacy_compat_category == "true_success"


def test_legacy_compat_leg():
    signals = derive_v2_signals(
        {"mechanism_identified": "CORRECT", "commitments_extracted": "CORRECT",
         "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT"},
        code_correct=False, commitments_source="explicit",
    )
    assert signals.legacy_compat_category == "leg"
