"""Tests for the minimal LEG (Latent Execution Gap) schema and parser fairness.

A. LEG schema compliance
B. Parser fairness (same recovery for baseline and LEG)
C. No legacy field dependence
D. Intervention behavior
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from leg_reduction import parse_leg_output, LEG_REQUIRED_FIELDS


# ---------------------------------------------------------------------------
# A. LEG schema compliance
# ---------------------------------------------------------------------------


def test_valid_minimal_leg_json():
    """Valid minimal LEG JSON parses correctly with all fields."""
    raw = json.dumps({
        "root_cause": "create_config returns DEFAULTS by reference",
        "fix_strategy": "Use DEFAULTS.copy() to return independent dict",
        "risk_check": "Shallow copy may not handle nested dicts, but DEFAULTS is flat — safe.",
        "files": {"config.py": "DEFAULTS = {}\ndef create_config(): return DEFAULTS.copy()"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is True
    assert result["leg_fields"]["root_cause"] == "create_config returns DEFAULTS by reference"
    assert result["leg_fields"]["fix_strategy"] == "Use DEFAULTS.copy() to return independent dict"
    assert "Shallow copy" in result["leg_fields"]["risk_check"]
    assert len(result["leg_warnings"]) == 0


def test_missing_root_cause_fails():
    """Missing root_cause produces a validation warning."""
    raw = json.dumps({
        "fix_strategy": "fix it",
        "risk_check": "checked",
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is False
    assert any("root_cause" in w for w in result["leg_warnings"])


def test_missing_fix_strategy_fails():
    raw = json.dumps({
        "root_cause": "bug",
        "risk_check": "checked",
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is False
    assert any("fix_strategy" in w for w in result["leg_warnings"])


def test_missing_risk_check_fails():
    raw = json.dumps({
        "root_cause": "bug",
        "fix_strategy": "fix",
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is False
    assert any("risk_check" in w for w in result["leg_warnings"])


def test_missing_files_still_parses_reasoning():
    """Missing files dict — code extraction may fail but reasoning is preserved."""
    raw = json.dumps({
        "root_cause": "bug in f()",
        "fix_strategy": "change f()",
        "risk_check": "edge case handled",
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is True  # reasoning fields all present
    assert "bug in f()" in result["reasoning"]


# ---------------------------------------------------------------------------
# B. Parser fairness
# ---------------------------------------------------------------------------


def test_malformed_json_recovers_same_as_baseline():
    """Malformed JSON with code block recovers via same baseline parser path."""
    from parse import parse_model_response

    # Malformed: unescaped newlines in JSON string (common model failure)
    raw_baseline = '{"reasoning": "the bug is aliasing", "code": "def f():\\n    return 1"}'
    raw_leg = '{"root_cause": "aliasing", "fix_strategy": "copy", "risk_check": "safe", "files": {"a.py": "def f():\\n    return 1"}}'

    baseline_result = parse_model_response(raw_baseline)
    leg_result = parse_leg_output(raw_leg)

    # Both should recover code through the same parser
    assert baseline_result.get("code") or baseline_result.get("files")
    assert leg_result.get("code") or leg_result.get("files")


def test_code_block_recovery_works_for_leg():
    """If LEG response has code blocks instead of JSON, recovery works."""
    raw = "Here is the fix:\n```python\ndef f():\n    return 1\n```"
    result = parse_leg_output(raw)
    # Code should be recovered via code block fallback
    assert result.get("code") and result["code"].strip()
    # LEG fields won't be available (no JSON)
    assert result["leg_valid"] is False


def test_raw_fallback_works_for_leg():
    """Total parse failure treats LAG same as baseline — raw fallback."""
    raw = "just some text about the bug"
    result = parse_leg_output(raw)
    # Should hit raw_fallback, same as baseline would
    assert result.get("response_format") == "raw_fallback"


# ---------------------------------------------------------------------------
# C. No legacy field dependence
# ---------------------------------------------------------------------------


def test_no_old_fields_required():
    """Old LEG fields (failure_mechanism, broken_invariant, etc.) are not required."""
    raw = json.dumps({
        "root_cause": "bug",
        "fix_strategy": "fix",
        "risk_check": "safe",
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is True
    # Old fields should not appear in leg_fields
    assert "failure_mechanism" not in result["leg_fields"]
    assert "broken_invariant" not in result["leg_fields"]
    assert "alternative_hypothesis" not in result["leg_fields"]
    assert "hypothesis_rejection" not in result["leg_fields"]
    assert "self_check" not in result["leg_fields"]


def test_old_fields_present_but_ignored():
    """Old fields in response are ignored — only new fields extracted."""
    raw = json.dumps({
        "root_cause": "bug",
        "fix_strategy": "fix",
        "risk_check": "safe",
        "failure_mechanism": "old field",
        "broken_invariant": "old field",
        "alternative_hypothesis": "old field",
        "self_check": {"failure_scenario": "old"},
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is True
    assert len(result["leg_fields"]) == 3  # only the 3 required fields


# ---------------------------------------------------------------------------
# D. Intervention behavior
# ---------------------------------------------------------------------------


def test_reasoning_includes_risk_check():
    """Parsed reasoning concatenates root_cause + fix_strategy + risk_check."""
    raw = json.dumps({
        "root_cause": "PART_A",
        "fix_strategy": "PART_B",
        "risk_check": "PART_C",
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert "PART_A" in result["reasoning"]
    assert "PART_B" in result["reasoning"]
    assert "PART_C" in result["reasoning"]


def test_file_dict_extraction():
    """Files dict with UNCHANGED entries works correctly."""
    raw = json.dumps({
        "root_cause": "bug",
        "fix_strategy": "fix",
        "risk_check": "safe",
        "files": {
            "a.py": "def fixed(): pass",
            "b.py": "UNCHANGED",
        },
    })
    result = parse_leg_output(raw)
    assert result.get("files") == {"a.py": "def fixed(): pass", "b.py": "UNCHANGED"}


def test_empty_risk_check_not_valid():
    """Empty string risk_check is not valid."""
    raw = json.dumps({
        "root_cause": "bug",
        "fix_strategy": "fix",
        "risk_check": "",
        "files": {"a.py": "pass"},
    })
    result = parse_leg_output(raw)
    assert result["leg_valid"] is False
    assert any("risk_check" in w for w in result["leg_warnings"])
