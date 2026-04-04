# Parser V2 Refactor Plan: Strict/Recovery Split

## Objective

Refactor `parse_generation_v2` in `parser_v2.py` into two explicitly separated parsing paths:

1. **STRICT** (`parse_generation_v2_strict`) — ground truth, no repair
2. **RECOVERY** (`parse_generation_v2_recover`) — controlled repair, diagnostic only

The pipeline uses STRICT for all decisions. RECOVERY is logged alongside for diagnostics
and future analysis of "what would recovery have saved."

## Current State

**File:** `parser_v2.py` (275 lines)

**Current function:** `parse_generation_v2(raw_response_text, condition) -> ParsedGenerationV2`

**Current pipeline (mixed strict + recovery):**
1. Empty check
2. `_strip_fences`
3. `_find_json_block(cleaned)` — if None, falls back to `_find_json_block(raw)` ← recovery behavior
4. `json.loads` — if fails, calls `_repair_triple_quotes` ← recovery behavior
5. Dict type check
6. Extract `files_dict`
7. `validate_generation_fields`
8. Return `ParsedGenerationV2`

**Problem:** Steps 3b and 4b silently mix recovery logic into the primary parse path.
There is no way to distinguish "model produced valid JSON" from "model produced broken
JSON that we repaired." This conflates ground-truth parse rate with repaired parse rate.

**Callers:**
- `execution_v2.py:82` — runtime (single call site)
- `tests/test_v2_unit.py` — 7 test functions
- `reasoning_v2.py` — imports `ParsedGenerationV2` dataclass only

---

## Step 1 — Shared Utilities (No Changes Needed)

The following are already pure, stateless functions at module scope:

| Function | Line | Purpose |
|---|---|---|
| `_strip_fences(text) -> str` | 39 | Strip markdown code fences |
| `_find_json_block(text) -> str or None` | 53 | Bracket-matched JSON extraction |
| `_repair_triple_quotes(text) -> (str, bool)` | 84 | Fix unescaped triple-quote docstrings |

No refactoring needed. Both parsers use them directly.

---

## Step 2 — Extend ParsedGenerationV2

Add 3 fields to the dataclass at `parser_v2.py:25-36`:

```python
parser_mode: str = "strict"          # "strict" | "recovery"
recovery_type: str | None = None     # None | "raw_block_extraction" | "triple_quote_fix" | "triple_quote_fix_raw"
strict_equivalent: bool = True       # True if recovery result matches what strict would produce
```

**Backwards-compatible:** Defaults match strict-parser behavior. All existing test assertions
pass without modification because existing code never checks these fields.

---

## Step 3 — Create parse_generation_v2_strict

### Signature

```python
def parse_generation_v2_strict(raw_response_text: str, condition: str) -> ParsedGenerationV2
```

### Pipeline (linear, no branching)

```
1. schema_variant = CONDITION_TO_SCHEMA.get(condition, condition)
2. Empty check → FAIL "empty_response"
3. cleaned = _strip_fences(raw_response_text)
4. json_str = _find_json_block(cleaned)       ← cleaned text ONLY, no fallback to raw
5. If json_str is None → FAIL "no_json_block"
6. parsed = json.loads(json_str)              ← single attempt, no retry
7. If JSONDecodeError → FAIL "json_decode_error: {detail}"
8. If not isinstance(parsed, dict) → FAIL "not_dict"
9. Extract files_dict from parsed["files"] if present
10. val_status, val_errors = validate_generation_fields(parsed, schema_variant)
11. parse_status = "success" if val_status == "valid" else val_status
12. Return ParsedGenerationV2 with:
       parser_mode = "strict"
       parser_variant = "parser_v2_strict"
       recovery_type = None
       strict_equivalent = True
```

### What strict DOES NOT do

- No `_find_json_block(raw_response_text)` fallback (current line 210)
- No `_repair_triple_quotes` call (current lines 223-230)
- No second `json.loads` attempt

### Source mapping

Extracted from current lines 192-274, removing lines 210 and 222-230.

---

## Step 4 — Create parse_generation_v2_recover

### Signature

```python
def parse_generation_v2_recover(raw_response_text: str, condition: str) -> ParsedGenerationV2
```

### Pipeline (cascading recovery phases)

```
Phase A — strict logic (passthrough)
    1. Empty check → FAIL
    2. cleaned = _strip_fences(raw_response_text)
    3. json_str = _find_json_block(cleaned)
    4. If found → json.loads
    5. If succeeds → validate → return with:
           parser_mode = "recovery"
           parser_variant = "parser_v2_recovery_passthrough"
           recovery_type = None
           strict_equivalent = True

Phase B — raw block extraction
    6. json_str = _find_json_block(raw_response_text)    ← fallback to unfenced text
    7. If found → json.loads
    8. If succeeds → validate → return with:
           recovery_type = "raw_block_extraction"
           strict_equivalent = False

Phase C — triple-quote repair on cleaned text
    9. repaired_str, was_repaired = _repair_triple_quotes(cleaned)
    10. If was_repaired → json.loads(repaired_str)
    11. If succeeds → validate → return with:
            recovery_type = "triple_quote_fix"
            strict_equivalent = False

Phase D — triple-quote repair on raw text
    12. repaired_str, was_repaired = _repair_triple_quotes(raw_response_text)
    13. If was_repaired → json.loads(repaired_str)
    14. If succeeds → validate → return with:
            recovery_type = "triple_quote_fix_raw"
            strict_equivalent = False

Phase E — all recovery failed
    15. Return FAIL with parse_error = "recovery_failed: {last_error}"
```

### Key invariants

- `parse_status` for recovered results: `"success"` if schema validates, `"partial"` or
  `"invalid"` if schema fails. Recovery repairs JSON formatting, not missing fields.
- `recovery_type` is ALWAYS set for non-passthrough results. Never silently succeeds.
- `strict_equivalent = True` ONLY in Phase A (passthrough).

---

## Step 5 — Internal Shared Helper

To avoid duplicating validation/assembly logic between strict and recover:

```python
def _validate_and_build(
    parsed: dict,
    schema_variant: str,
    raw_response_text: str,
    parser_mode: str,
    parser_variant: str,
    recovery_type: str | None,
    strict_equivalent: bool,
) -> ParsedGenerationV2
```

This helper performs:
1. `isinstance(parsed, dict)` check
2. `files_dict` extraction
3. `validate_generation_fields(parsed, schema_variant)`
4. Build and return `ParsedGenerationV2`

Both `_strict` and `_recover` call this after successful `json.loads`.

---

## Step 6 — Recovery Decision Tree

```
parse_generation_v2_recover(raw, condition)
│
├─ Phase A: _strip_fences → _find_json_block(cleaned) → json.loads
│  ├─ SUCCESS → strict_equivalent=True, recovery_type=None
│  └─ FAIL ↓
│
├─ Phase B: _find_json_block(raw)
│  ├─ SUCCESS → recovery_type="raw_block_extraction"
│  └─ FAIL ↓
│
├─ Phase C: _repair_triple_quotes(cleaned) → json.loads
│  ├─ SUCCESS → recovery_type="triple_quote_fix"
│  └─ FAIL ↓
│
├─ Phase D: _repair_triple_quotes(raw) → json.loads
│  ├─ SUCCESS → recovery_type="triple_quote_fix_raw"
│  └─ FAIL ↓
│
└─ HARD FAIL: parse_error="recovery_failed"
```

---

## Step 7 — Failure Taxonomy

### Strict errors

| Error | Trigger |
|---|---|
| `empty_response` | raw_response_text is empty/whitespace |
| `no_json_block` | `_find_json_block(cleaned)` returns None |
| `json_decode_error: {detail}` | `json.loads` raises JSONDecodeError |
| `not_dict` | parsed value is list, str, int, etc. |
| `schema_validation_failed: {errors}` | `validate_generation_fields` returns invalid/partial |

### Recovery-specific errors

| Error | Trigger |
|---|---|
| `recovery_failed` | all 4 phases exhausted |

Recovery inherits strict error strings for Phase A (passthrough case).

---

## Step 8 — Integration Plan

### Legacy wrapper (preserve existing callers)

`parse_generation_v2` becomes a thin wrapper:

```python
def parse_generation_v2(raw_response_text: str, condition: str) -> ParsedGenerationV2:
    """Legacy wrapper -- delegates to strict parser."""
    return parse_generation_v2_strict(raw_response_text, condition)
```

All existing test imports and calls continue to work unchanged.

### execution_v2.py changes (line 82)

Replace:
```python
parsed_gen = parse_generation_v2(raw_response, condition)
```

With:
```python
from parser_v2 import parse_generation_v2_strict, parse_generation_v2_recover

# STAGE 3: Parse (strict = ground truth, recovery = diagnostic)
strict_result = parse_generation_v2_strict(raw_response, condition)
recovery_result = parse_generation_v2_recover(raw_response, condition)

# Pipeline uses STRICT only
parsed_gen = strict_result
```

### Diagnostic logging (add to ev dict in assemble_v2_result or execution_v2)

```python
ev["v2_recovery_diagnostic"] = {
    "strict_status": strict_result.parse_status,
    "recovery_status": recovery_result.parse_status,
    "recovery_type": recovery_result.recovery_type,
    "strict_equivalent": recovery_result.strict_equivalent,
    "recovery_changed_outcome": (
        strict_result.parse_status == "failed"
        and recovery_result.parse_status in ("success", "partial")
    ),
}
```

This gives us the metric: "how often would recovery have saved a strict failure" without
ever letting recovery influence the pipeline.

---

## Step 9 — Test Plan

### New test file: tests/test_parser_v2_split.py

### Strict PASS tests (carried over from existing)

- Valid JSON, all fields -> `parse_status="success"`, `parser_mode="strict"`
- Valid JSON with extra fields -> success, extras preserved
- Fenced JSON (` ```json ... ``` `) -> success (fence stripping is part of strict)

### Strict FAIL tests

- `""` -> `parse_error="empty_response"`
- `"just some text"` -> `parse_error="no_json_block"`
- `"{bad json"` -> `parse_error` starts with `"json_decode_error"`
- `'[1, 2, 3]'` -> `parse_error="not_dict"`
- Missing required field (e.g. no `files`) -> `parse_status="invalid"`
- Raw response with `""""docstring"""` in files value -> **strict MUST fail** (no repair)
- JSON block only findable in raw text (not after fence stripping) -> **strict MUST fail** (no raw fallback)

### Recovery PASS tests

- Valid JSON -> `strict_equivalent=True`, `recovery_type=None`
- Triple-quote case from nano ablation -> `recovery_type="triple_quote_fix"`, `strict_equivalent=False`
- JSON block in raw but not in cleaned -> `recovery_type="raw_block_extraction"`, `strict_equivalent=False`
- Fenced JSON -> `strict_equivalent=True` (Phase A handles it)

### Recovery FAIL tests

- Missing required fields (recovery parses JSON but schema rejects) -> `parse_status="invalid"`
- `'[1, 2, 3]'` -> not_dict error
- Completely unparseable text -> `parse_error="recovery_failed"`

### Strict/Recovery agreement tests

- For every valid JSON input: assert `strict.parse_status == recovery.parse_status` AND `recovery.strict_equivalent == True`
- For triple-quote input: assert `strict.parse_status == "failed"` AND `recovery.parse_status in ("success", "partial")` AND `recovery.strict_equivalent == False`

### Regression test using real ablation data

- Load the 6 nano parse-failure raw responses from `logs/v2_ablation_nano/2026-03-29_20-32-44_v2_ablation_nano_002/calls/`
- Known cases: `partial_update_b/leg_reduction_v2`, `stale_cache_b/leg_reduction_v2`, `mutable_default_a/leg_reduction_lean_v2`, `mutable_default_b/baseline_v2`, `effect_order_b/leg_reduction_v2`, `retry_dup_c/leg_reduction_v2`
- Assert strict fails on all 6
- Assert recovery succeeds on all 6 (with `recovery_type="triple_quote_fix"`)
- Assert `strict_equivalent=False` on all 6

---

## Step 10 — File Change Summary

| File | Change |
|---|---|
| `parser_v2.py` | Add 3 fields to `ParsedGenerationV2`. Add `_validate_and_build` helper. Add `parse_generation_v2_strict`. Add `parse_generation_v2_recover`. Reduce `parse_generation_v2` to wrapper. |
| `execution_v2.py` | Import strict + recover. Call both. Log diagnostic. Pipeline uses strict only. |
| `tests/test_v2_unit.py` | Existing tests unchanged (call `parse_generation_v2` which wraps strict). |
| `tests/test_parser_v2_split.py` | New file. All strict/recovery/agreement/regression tests. |

No other files change. `reasoning_v2.py` imports only `ParsedGenerationV2` which gains
default-valued fields (backwards compatible). `contracts_v2.py` is untouched.
