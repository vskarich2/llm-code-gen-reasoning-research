"""Tests for three-tier parser: execution, format, recovery."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parser_v2 import (
    parse_v2_execution, parse_v2_format, parse_v2_recovery,
    parse_generation_v2, ParsedGenerationV2,
    _find_json_block, _count_json_objects, _fix_invalid_escapes,
)

# ── Helpers ──

VALID_BL = json.dumps({
    "root_cause": "create_config returns DEFAULTS by reference causing aliasing",
    "fix_strategy": "use DEFAULTS.copy() to return an independent dict",
    "files": {"config.py": "def create_config(): return DEFAULTS.copy()"},
})

VALID_LEG = json.dumps({
    "root_cause": "create_config returns DEFAULTS by reference causing aliasing",
    "code_commitments": ["create_config must return copy"],
    "fix_strategy": "use DEFAULTS.copy() to return an independent dict",
    "risk_check": "safe because flat dict",
    "files": {"config.py": "def create_config(): return DEFAULTS.copy()"},
})

FENCED = f"```json\n{VALID_BL}\n```"
WITH_COMMENTARY = f"Here is the fix:\n{VALID_BL}\nLet me know if this works!"
TWO_OBJECTS = '{"a": 1}\n{"b": 2}'
# Real triple-quote pattern from nano: model uses \\n (literal backslash-n) for
# newlines inside JSON strings, but leaves """ unescaped.
TRIPLE_QUOTE_BROKEN = (
    '{\n  "root_cause": "' + 'x' * 20
    + '",\n  "fix_strategy": "' + 'y' * 20
    + '",\n  "files": {\n    "a.py": """"Module docstring."""\\n\\ndef foo():\\n    pass\\n"'
    + '\n  }\n}'
)

# Also load a real nano failure if available (used by regression tests below)
_REAL_NANO_CALLS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "logs/v2_ablation_nano/2026-03-29_20-32-44_v2_ablation_nano_002/calls",
)
_HAS_REAL_DATA = os.path.isdir(_REAL_NANO_CALLS_DIR)


# ============================================================
# _find_json_block
# ============================================================

def test_find_empty():
    assert _find_json_block("") == (None, -1)

def test_find_no_braces():
    assert _find_json_block("no braces here") == (None, -1)

def test_find_unbalanced():
    assert _find_json_block("{") == (None, -1)

def test_find_minimal():
    assert _find_json_block("{}") == ("{}", 2)

def test_find_with_surrounding():
    block, end = _find_json_block("text { } more")
    assert block == "{ }"
    assert end == 8

def test_find_brace_in_string():
    text = '{"a": "}"}'
    block, end = _find_json_block(text)
    assert block == text
    assert end == len(text)

def test_find_returns_first():
    block, end = _find_json_block('{"a":1} {"b":2}')
    assert block == '{"a":1}'
    assert end == 7


# ============================================================
# _count_json_objects
# ============================================================

def test_count_zero():
    assert _count_json_objects("no json") == 0

def test_count_one():
    assert _count_json_objects('{"a":1}') == 1

def test_count_two():
    assert _count_json_objects('{"a":1}\n{"b":2}') == 2

def test_count_nested_is_one():
    assert _count_json_objects('{"a":{"b":1}}') == 1


# ============================================================
# _fix_invalid_escapes
# ============================================================

def test_fix_escapes_valid():
    text = r'"hello\nworld"'
    fixed, did = _fix_invalid_escapes(text)
    assert not did

def test_fix_escapes_invalid():
    text = r'"pattern: \s+"'
    fixed, did = _fix_invalid_escapes(text)
    assert did
    assert r"\\s" in fixed


# ============================================================
# EXECUTION PARSER
# ============================================================

def test_exec_valid_bare():
    r = parse_v2_execution(VALID_BL, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is True
    assert r.parse_status == "success"
    assert r.parser_tier == "execution"

def test_exec_valid_fenced():
    r = parse_v2_execution(FENCED, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is True

def test_exec_valid_with_commentary():
    r = parse_v2_execution(WITH_COMMENTARY, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is True

def test_exec_empty():
    r = parse_v2_execution("", "baseline_v2")
    assert r.parse_valid is False
    assert r.parse_error == "empty_response"

def test_exec_no_json():
    r = parse_v2_execution("just text", "baseline_v2")
    assert r.parse_valid is False
    assert r.parse_error == "no_json_block"

def test_exec_invalid_json():
    r = parse_v2_execution("{bad json", "baseline_v2")
    assert r.parse_valid is False
    # _find_json_block won't find balanced block
    assert "no_json_block" in r.parse_error or "json_decode" in r.parse_error

def test_exec_not_dict():
    # Arrays have no '{', so _find_json_block returns None -> no_json_block
    r = parse_v2_execution("[1, 2, 3]", "baseline_v2")
    assert r.parse_valid is False
    assert r.parse_error == "no_json_block"

def test_exec_multiple_json():
    r = parse_v2_execution(TWO_OBJECTS, "baseline_v2")
    assert r.parse_valid is False
    assert r.parse_error == "multiple_json_objects"

def test_exec_triple_quote_no_repair():
    r = parse_v2_execution(TRIPLE_QUOTE_BROKEN, "baseline_v2")
    assert r.parse_valid is False  # execution does NOT repair

def test_exec_schema_separation_missing_files():
    raw = json.dumps({"root_cause": "x" * 20, "fix_strategy": "y" * 20})
    r = parse_v2_execution(raw, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is False
    assert r.parse_status == "invalid"

def test_exec_schema_separation_short_field():
    raw = json.dumps({"root_cause": "short", "fix_strategy": "y" * 20, "files": {"a.py": "pass"}})
    r = parse_v2_execution(raw, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is False
    assert r.parse_status == "partial"

def test_exec_mis_extraction():
    raw = json.dumps({"unrelated": "data", "nothing": "useful"})
    r = parse_v2_execution(raw, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is False
    assert r.possible_mis_extraction is True  # missing 2+ required keys


# ============================================================
# FORMAT PARSER
# ============================================================

def test_fmt_valid_bare():
    r = parse_v2_format(VALID_BL, "baseline_v2")
    assert r.format_valid is True
    assert r.parse_valid is True
    assert r.schema_valid is True

def test_fmt_fenced_fails():
    r = parse_v2_format(FENCED, "baseline_v2")
    assert r.format_valid is False
    assert r.format_error == "fenced_output"

def test_fmt_extra_text_fails():
    r = parse_v2_format(WITH_COMMENTARY, "baseline_v2")
    assert r.format_valid is False
    assert r.format_error == "extra_text"

def test_fmt_trailing_text():
    raw = VALID_BL + "\nDone!"
    r = parse_v2_format(raw, "baseline_v2")
    assert r.format_valid is False
    assert r.format_error == "extra_text"

def test_fmt_multiple_json():
    # Extra text check fires before multi-json guard (second object is "extra text")
    r = parse_v2_format(TWO_OBJECTS, "baseline_v2")
    assert r.format_valid is False
    assert r.format_error in ("extra_text", "multiple_json_objects")

def test_fmt_empty():
    r = parse_v2_format("", "baseline_v2")
    assert r.format_valid is False
    assert r.format_error == "empty_response"


# ============================================================
# RECOVERY PARSER
# ============================================================

def test_rec_passthrough():
    r = parse_v2_recovery(VALID_BL, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is True
    assert r.execution_equivalent is True
    assert r.recovery_type is None
    assert any("phase_a:SUCCESS" in s for s in r.recovery_steps)

def test_rec_triple_quote():
    r = parse_v2_recovery(TRIPLE_QUOTE_BROKEN, "baseline_v2")
    assert r.parse_valid is True
    assert r.recovery_type in ("triple_quote_fix", "triple_quote_fix_raw")
    assert r.execution_equivalent is False

def test_rec_fails_on_garbage():
    r = parse_v2_recovery("absolutely no json anywhere", "baseline_v2")
    assert r.parse_valid is False
    assert r.parse_error == "recovery_failed"
    assert len(r.recovery_steps) >= 4  # multiple phases attempted

def test_rec_does_not_invent_fields():
    raw = json.dumps({"root_cause": "x" * 20, "fix_strategy": "y" * 20})
    r = parse_v2_recovery(raw, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is False  # missing "files" -- recovery did NOT invent it

def test_rec_multiple_json_rejected():
    r = parse_v2_recovery(TWO_OBJECTS, "baseline_v2")
    assert r.parse_valid is False  # recovery does NOT merge

def test_rec_not_dict_rejected():
    # Arrays have no '{', so no JSON block found in any phase
    r = parse_v2_recovery("[1, 2, 3]", "baseline_v2")
    assert r.parse_valid is False
    assert r.parse_error == "recovery_failed"

def test_rec_code_to_files_rename():
    raw = json.dumps({
        "root_cause": "x" * 20, "fix_strategy": "y" * 20,
        "code": {"config.py": "pass"},
    })
    r = parse_v2_recovery(raw, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is True
    assert r.schema_normalization_applied is True
    assert r.recovery_type == "code_to_files_rename"
    assert r.full_json["files"] == {"config.py": "pass"}
    assert "code" not in r.full_json


# ============================================================
# CROSS-TIER AGREEMENT
# ============================================================

def test_all_tiers_agree_on_valid():
    ex = parse_v2_execution(VALID_BL, "baseline_v2")
    fmt = parse_v2_format(VALID_BL, "baseline_v2")
    rec = parse_v2_recovery(VALID_BL, "baseline_v2")
    assert ex.parse_valid and fmt.parse_valid and rec.parse_valid
    assert ex.schema_valid and fmt.schema_valid and rec.schema_valid
    assert fmt.format_valid is True

def test_fenced_exec_pass_fmt_fail():
    ex = parse_v2_execution(FENCED, "baseline_v2")
    fmt = parse_v2_format(FENCED, "baseline_v2")
    rec = parse_v2_recovery(FENCED, "baseline_v2")
    assert ex.parse_valid is True
    assert fmt.format_valid is False
    assert rec.parse_valid is True

def test_triple_quote_exec_fail_rec_pass():
    ex = parse_v2_execution(TRIPLE_QUOTE_BROKEN, "baseline_v2")
    rec = parse_v2_recovery(TRIPLE_QUOTE_BROKEN, "baseline_v2")
    assert ex.parse_valid is False
    assert rec.parse_valid is True
    assert rec.execution_equivalent is False

def test_invariant_exec_subset_recovery():
    """If execution passes, recovery must also pass."""
    inputs = [VALID_BL, FENCED, WITH_COMMENTARY, VALID_LEG]
    for raw in inputs:
        cond = "leg_reduction_v2" if "code_commitments" in raw else "baseline_v2"
        ex = parse_v2_execution(raw, cond)
        rec = parse_v2_recovery(raw, cond)
        if ex.parse_valid:
            assert rec.parse_valid, f"Invariant violated on: {raw[:50]}"


# ============================================================
# MULTIPLE-JSON GUARD (all tiers)
# ============================================================

def test_multi_json_all_tiers():
    for parser in [parse_v2_execution, parse_v2_format, parse_v2_recovery]:
        r = parser(TWO_OBJECTS, "baseline_v2")
        assert r.parse_valid is False, f"{parser.__name__} should reject multiple JSON"


# ============================================================
# DETERMINISM
# ============================================================

def test_recovery_deterministic():
    for _ in range(10):
        r = parse_v2_recovery(TRIPLE_QUOTE_BROKEN, "baseline_v2")
        assert r.recovery_type in ("triple_quote_fix", "triple_quote_fix_raw")
        assert r.parse_valid is True


# ============================================================
# LEGACY WRAPPER
# ============================================================

def test_legacy_wrapper():
    r = parse_generation_v2(VALID_BL, "baseline_v2")
    assert r.parse_valid is True
    assert r.schema_valid is True
    assert r.parser_tier == "execution"


# ============================================================
# REGRESSION: real nano ablation data
# ============================================================

_REAL_FAIL_CASES = [
    ("partial_update_b", "leg_reduction_v2"),
    ("stale_cache_b", "leg_reduction_v2"),
    ("mutable_default_a", "leg_reduction_lean_v2"),
    ("mutable_default_b", "baseline_v2"),
    ("effect_order_b", "leg_reduction_v2"),
    ("retry_dup_c", "leg_reduction_v2"),
]


def _load_real_response(case_id, cond):
    """Load a raw response from the nano ablation calls directory."""
    import json as _json
    for fname in sorted(os.listdir(_REAL_NANO_CALLS_DIR)):
        path = os.path.join(_REAL_NANO_CALLS_DIR, fname)
        with open(path) as f:
            call = _json.loads(f.read())
        if (call.get("case_id") == case_id
                and call.get("condition") == cond
                and call.get("phase") == "generation"):
            return call["response_raw"]
    return None


@pytest.mark.skipif(not _HAS_REAL_DATA, reason="nano ablation data not present")
@pytest.mark.parametrize("case_id,cond", _REAL_FAIL_CASES)
def test_regression_real_nano_failures(case_id, cond):
    """Real nano parse failures: exec FAIL, format FAIL, recovery PASS."""
    raw = _load_real_response(case_id, cond)
    assert raw is not None, f"Could not load {case_id}/{cond}"

    ex = parse_v2_execution(raw, cond)
    fmt = parse_v2_format(raw, cond)
    rec = parse_v2_recovery(raw, cond)

    assert ex.parse_valid is False, f"execution should fail for {case_id}"
    assert fmt.format_valid is False, f"format should fail for {case_id}"
    assert rec.parse_valid is True, f"recovery should succeed for {case_id}"
    assert rec.recovery_type == "triple_quote_fix", f"expected triple_quote_fix for {case_id}"
    assert rec.execution_equivalent is False
