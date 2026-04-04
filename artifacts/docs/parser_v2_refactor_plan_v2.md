# Parser V2 Refactor Plan v2: Strict/Recovery Split (Revised)

This revision addresses 7 critical weaknesses in the v1 plan. Changes are marked with
**[REV]** to distinguish from carried-over design.

---

## 1. Revised Architecture

### Design principle

The parser is an **experimental variable**, not just infrastructure. It determines:

- **STRICT parse rate** = ground truth model capability. "Can the model produce valid,
  instruction-following JSON output?" This is a measurement of the model, not the system.
- **RECOVERY parse rate** = upper bound capability. "If we help the model with
  serialization, what could it achieve?" This bounds the serialization tax.
- **Recoverable failure rate** = `(strict_failed AND recovery_succeeded) / total`.
  This is the first-class metric that quantifies how much performance is lost to
  formatting rather than reasoning.

STRICT and RECOVERY are co-evaluated on every call. STRICT drives the pipeline.
RECOVERY is logged for analysis. They never interact.

### Separation guarantee

```
execution_v2.run_v2():
    raw_response = call_model(...)

    strict_result  = parse_generation_v2_strict(raw_response, condition)
    recovery_result = parse_generation_v2_recover(raw_response, condition)

    parsed_gen = strict_result          # <-- ONLY strict enters pipeline
    # recovery_result logged to ev dict, never consumed by stages 4-9
```

---

## 2. Updated ParsedGenerationV2 Schema

**[REV]** Adds `parse_valid` and `schema_valid` booleans to decouple JSON correctness
from contract correctness. The old `parse_status` conflated both.

```python
@dataclass
class ParsedGenerationV2:
    # --- existing fields (unchanged) ---
    parse_status: str                   # "success" | "partial" | "invalid" | "failed"
    schema_variant: str                 # "baseline_v2" | "leg_v2" | "lean_v2"
    full_json: dict | None              # complete parsed JSON -- AUTHORITATIVE
    files_dict: dict | None             # extracted files dict
    parse_error: str | None             # specific error string
    raw_response_text: str              # original raw (logging only, NOT for reparsing)
    parser_variant: str = "parser_v2_generation"
    validation_status: str = ""         # "valid" | "partial" | "invalid"
    validation_errors: list[str] = field(default_factory=list)

    # --- new fields ---
    parse_valid: bool = False           # [REV] True iff json.loads succeeded AND type is dict
    schema_valid: bool = False          # [REV] True iff validate_generation_fields == "valid"
    parser_mode: str = "strict"         # "strict" | "recovery"
    recovery_type: str | None = None    # None | specific recovery label
    recovery_steps: list[str] = field(default_factory=list)  # [REV] ordered list of steps applied
    strict_equivalent: bool = True      # True only if recovery produced same result as strict
    extra_text_detected: bool = False   # [REV] True if non-whitespace exists outside JSON block
```

### Field semantics

| Field | Set by | Meaning |
|---|---|---|
| `parse_valid` | Both | JSON deserialized to a dict. Independent of schema. |
| `schema_valid` | Both | All required fields present with correct types. Independent of JSON. |
| `parse_status` | Both | Derived: `"success"` iff `parse_valid AND schema_valid`. `"failed"` if `not parse_valid`. Otherwise inherits from `validation_status`. |
| `parser_mode` | Both | Which parser produced this result. |
| `recovery_type` | Recovery | Specific recovery that succeeded. None for passthrough. |
| `recovery_steps` | Recovery | **[REV]** Full audit trail: `["strip_fences", "find_json_block_cleaned", "json_loads"]` or `["strip_fences", "find_json_block_cleaned:FAIL", "find_json_block_raw", "json_loads"]` etc. |
| `strict_equivalent` | Recovery | True ONLY if recovery Phase A succeeded (identical to strict). |
| `extra_text_detected` | Strict | **[REV]** True if text outside JSON block found. |

### Derivation rules for parse_status

```
if not parse_valid:
    parse_status = "failed"
elif schema_valid:
    parse_status = "success"
else:
    parse_status = validation_status   # "partial" or "invalid"
```

This is a pure derivation. `parse_valid` and `schema_valid` are the ground truth.

---

## 3. Strict Parser (Truly Strict)

### Signature

```python
def parse_generation_v2_strict(raw_response_text: str, condition: str) -> ParsedGenerationV2
```

### Pipeline

```
 1. schema_variant = CONDITION_TO_SCHEMA.get(condition, condition)
 2. If empty/whitespace -> FAIL "empty_response"
 3. cleaned = _strip_fences(raw_response_text)
 4. json_str = _find_json_block(cleaned)
 5. If json_str is None -> FAIL "no_json_block"
 6. [REV] Extra-text check:
       before = cleaned[:cleaned.index(json_str[0])].strip()  (text before JSON)
       after  = cleaned[cleaned.index(json_str[0]) + len(json_str):].strip()  (text after JSON)
       extra_text_detected = bool(before or after)
       If extra_text_detected -> FAIL "extra_text_outside_json"
 7. parsed = json.loads(json_str)
 8. If JSONDecodeError -> FAIL "json_decode_error: {detail}"
 9. If not isinstance(parsed, dict) -> FAIL "not_dict"
10. parse_valid = True
11. files_dict extraction
12. val_status, val_errors = validate_generation_fields(parsed, schema_variant)
13. schema_valid = (val_status == "valid")
14. Derive parse_status
15. Return ParsedGenerationV2 with parser_mode="strict"
```

### [REV] What makes this truly strict

The v1 plan allowed fence stripping + JSON block extraction, meaning a response like:

```
Here is my answer:
```json
{"root_cause": "...", "files": {...}}
```
Let me know if you need changes!
```

...would pass strict. That is NOT strict. The model did not follow the output format
instruction (which says: output JSON only, no extra text).

**New rule (step 6):** After fence stripping and JSON block extraction, verify that
`cleaned == json_str` (ignoring whitespace). If there is ANY non-whitespace text
before or after the JSON block, strict FAILS with `extra_text_outside_json`.

**Exception:** Markdown fences are tolerated because they are a common, unambiguous
transport artifact. The model clearly intended to produce JSON. But fences are the ONLY
tolerated wrapper -- any other text is a format violation.

**Rationale:** Strict measures "did the model follow the output instruction exactly."
Extra text means it did not. This is the ground truth for instruction-following capability.

### Strict DOES NOT

- Fall back to `_find_json_block(raw_response_text)`
- Call `_repair_triple_quotes`
- Retry `json.loads`
- Accept extra text outside JSON
- Accept fenced text with surrounding commentary

---

## 4. Recovery Parser (Expanded)

### Signature

```python
def parse_generation_v2_recover(raw_response_text: str, condition: str) -> ParsedGenerationV2
```

### [REV] Recovery Transformation Whitelist

Recovery may apply ONLY transformations from this whitelist. Each transformation has
a label that is recorded in `recovery_steps` and (if it was the decisive one) in
`recovery_type`.

#### Category 1: TRANSPORT CLEANUP

| Label | Transformation | Justification |
|---|---|---|
| `strip_fences` | Remove ` ```json ... ``` ` wrappers | Unambiguous transport artifact |
| `strip_surrounding_text` | Remove non-JSON text before/after the JSON block | Model produced valid JSON but added commentary |
| `normalize_whitespace` | Strip leading/trailing whitespace | Never changes semantics |

#### Category 2: ESCAPE REPAIR

| Label | Transformation | Justification |
|---|---|---|
| `triple_quote_fix` | Re-escape `"""..."""` inside JSON string values | Known nano/4o-mini failure pattern; content is unambiguous |
| `backslash_quote_fix` | Fix `\"\"\"` that should be `\\\"\\\"\\\"` | Over-escaped variant of same pattern |
| `invalid_escape_fix` | Fix `\1`, `\s` etc. that JSON rejects | Model wrote regex/Python escapes inside JSON strings |

#### Category 3: STRUCTURAL ISOLATION

| Label | Transformation | Justification |
|---|---|---|
| `raw_block_extraction` | `_find_json_block(raw_response_text)` after cleaned extraction failed | Fence stripping may have corrupted the text |
| `embedded_json_extraction` | Extract JSON from within explanation text | Model wrapped JSON in natural language |

#### Category 4: FIELD NORMALIZATION (limited, unambiguous only)

| Label | Transformation | Justification |
|---|---|---|
| `code_to_files_rename` | Rename top-level `"code"` key to `"files"` if `"files"` absent and `"code"` is a dict | Unambiguous intent; some models use `"code"` instead of `"files"` |

#### NOT ALLOWED (explicit exclusion list)

| Forbidden | Reason |
|---|---|
| Inventing missing required fields | Hallucination |
| Merging multiple JSON candidates | Ambiguity |
| Reconstructing JSON from fragments | Interpretation |
| Semantic inference of model intent | Not deterministic |
| Coercing non-dict JSON to dict | Structural change |
| Guessing file paths | Hallucination |

### Recovery Pipeline (ordered, deterministic)

**[REV]** Expanded from 4 phases to 6. Each phase is attempted in order. First success wins.
Every phase records its label in `recovery_steps` regardless of success/failure.

```
Phase A -- Strict-equivalent (passthrough)
    1. cleaned = _strip_fences(raw)
    2. json_str = _find_json_block(cleaned)
    3. Verify no extra text (same check as strict step 6)
    4. json.loads(json_str)
    5. If ALL succeed -> return with:
           strict_equivalent = True
           recovery_type = None
           recovery_steps = ["strip_fences", "find_json_block_cleaned",
                             "extra_text_check:PASS", "json_loads"]

Phase B -- Embedded JSON extraction (extra text tolerated)
    6. json_str = _find_json_block(cleaned)    # already have this from Phase A
    7. Skip extra-text check (this is what Phase A rejected)
    8. json.loads(json_str)
    9. If succeeds -> return with:
           recovery_type = "strip_surrounding_text"
           strict_equivalent = False
           recovery_steps = [..., "extra_text_check:FAIL", "strip_surrounding_text", "json_loads"]

Phase C -- Raw block extraction (fence stripping corrupted text)
    10. json_str = _find_json_block(raw_response_text)
    11. json.loads(json_str)
    12. If succeeds -> return with:
            recovery_type = "raw_block_extraction"

Phase D -- Triple-quote repair on cleaned text
    13. repaired, was_repaired = _repair_triple_quotes(cleaned)
    14. If was_repaired -> json.loads(repaired)
    15. If succeeds -> return with:
            recovery_type = "triple_quote_fix"

Phase E -- Triple-quote repair on raw text
    16. repaired, was_repaired = _repair_triple_quotes(raw_response_text)
    17. If was_repaired -> json.loads(repaired)
    18. If succeeds -> return with:
            recovery_type = "triple_quote_fix_raw"

Phase F -- Invalid escape repair
    19. Apply regex to fix invalid JSON escapes (\s -> \\s, \1 -> \\1, etc.)
    20. Retry _find_json_block + json.loads on repaired text
    21. If succeeds -> return with:
            recovery_type = "invalid_escape_fix"

Phase G -- All recovery failed
    22. Return FAIL with parse_error = "recovery_failed"
        recovery_steps contains full audit trail of all attempted phases
```

### Determinism guarantee

**[REV]** The pipeline is a fixed-order cascade with no branching randomness. Given
identical input, it always executes the same phases in the same order and produces
the same output. This is guaranteed by construction (no random seeds, no heuristic
scoring, no candidate ranking).

**Required test:** Run recovery 100x on the same input, assert identical output every time.

---

## 5. Failure Taxonomy

### Strict errors

| Error | Trigger | parse_valid | schema_valid |
|---|---|---|---|
| `empty_response` | raw is empty/whitespace | False | False |
| `no_json_block` | `_find_json_block(cleaned)` returns None | False | False |
| `extra_text_outside_json` | **[REV]** non-whitespace before/after JSON block | False | False |
| `json_decode_error: {detail}` | `json.loads` raises JSONDecodeError | False | False |
| `not_dict` | parsed is list, str, int, etc. | False | False |
| (schema errors) | `validate_generation_fields` returns partial/invalid | True | False |

**[REV]** Note: schema errors are NOT parse failures. `parse_valid=True` but
`schema_valid=False`. The `parse_status` is "partial" or "invalid", not "failed".
This distinction matters: the model produced valid JSON (good serialization) but
wrong schema (bad instruction following). These are different failure modes.

### Recovery errors

| Error | Trigger |
|---|---|
| `recovery_failed` | all phases exhausted |

Recovery inherits strict error taxonomy for Phase A passthrough.

---

## 6. Metric Definitions

### Primary metrics (per condition, per model)

| Metric | Definition | What it measures |
|---|---|---|
| **strict_pass_rate** | `count(strict.parse_status == "success" AND exec_pass) / total` | Ground truth capability |
| **strict_parse_rate** | `count(strict.parse_valid) / total` | JSON serialization capability |
| **strict_schema_rate** | `count(strict.schema_valid) / count(strict.parse_valid)` | Schema compliance among parseable responses |
| **strict_format_rate** | `count(strict.parse_valid AND NOT strict.extra_text_detected) / total` | **[REV]** Instruction-following precision |
| **recovery_parse_rate** | `count(recovery.parse_valid) / total` | Upper bound after repair |
| **recoverable_failure_rate** | **[REV]** `count(strict.parse_status == "failed" AND recovery.parse_valid) / total` | Serialization tax |
| **recovery_type_distribution** | `Counter(recovery.recovery_type)` | Which repairs are needed |

### Derived metrics

| Metric | Definition | What it measures |
|---|---|---|
| **serialization_tax** | `recovery_parse_rate - strict_parse_rate` | Performance left on the table due to formatting |
| **format_violation_rate** | `strict_parse_rate - strict_format_rate` | **[REV]** Models that produce valid JSON but add commentary |
| **schema_gap** | `strict_parse_rate - strict_schema_rate * strict_parse_rate` | Models that serialize correctly but use wrong schema |

### How they are logged

In `execution_v2.py`, the ev dict gains:

```python
ev["v2_parse_diagnostic"] = {
    "strict_parse_valid": strict_result.parse_valid,
    "strict_schema_valid": strict_result.schema_valid,
    "strict_parse_error": strict_result.parse_error,
    "strict_extra_text": strict_result.extra_text_detected,
    "recovery_parse_valid": recovery_result.parse_valid,
    "recovery_schema_valid": recovery_result.schema_valid,
    "recovery_type": recovery_result.recovery_type,
    "recovery_steps": recovery_result.recovery_steps,
    "strict_equivalent": recovery_result.strict_equivalent,
    "recoverable": (
        not strict_result.parse_valid
        and recovery_result.parse_valid
    ),
}
```

This is a flat dict that can be aggregated directly into the metrics above.

---

## 7. Shared Internal Helper

```python
def _validate_and_build(
    parsed: dict,
    schema_variant: str,
    raw_response_text: str,
    *,
    parser_mode: str,
    parser_variant: str,
    recovery_type: str | None,
    recovery_steps: list[str],
    strict_equivalent: bool,
    extra_text_detected: bool,
) -> ParsedGenerationV2:
```

Performs:
1. `files_dict` extraction from `parsed["files"]`
2. `validate_generation_fields(parsed, schema_variant)`
3. Compute `parse_valid = True` (caller guarantees dict)
4. Compute `schema_valid = (val_status == "valid")`
5. Derive `parse_status`
6. Assemble and return `ParsedGenerationV2`

Both strict and recovery call this after successful `json.loads` + dict type check.
The dict check happens BEFORE calling this helper (caller responsibility), so
`parse_valid` is always True when this helper is invoked.

---

## 8. Integration Plan

### Legacy wrapper

```python
def parse_generation_v2(raw_response_text: str, condition: str) -> ParsedGenerationV2:
    """Legacy wrapper -- delegates to strict parser.

    NOTE: This now uses the truly-strict parser. Responses that previously
    passed via silent recovery (triple-quote repair, raw fallback) will now
    fail. This is intentional -- see parser_v2_refactor_plan_v2.md.
    """
    return parse_generation_v2_strict(raw_response_text, condition)
```

### execution_v2.py (line 82)

```python
from parser_v2 import parse_generation_v2_strict, parse_generation_v2_recover

# STAGE 3: Parse
strict_result = parse_generation_v2_strict(raw_response, condition)
recovery_result = parse_generation_v2_recover(raw_response, condition)

# Pipeline uses STRICT only
parsed_gen = strict_result

# Log diagnostic (never consumed by pipeline)
_log_parse_diagnostic(strict_result, recovery_result)
```

`_log_parse_diagnostic` builds the `v2_parse_diagnostic` dict from section 6 and
attaches it to the ev dict in stage 8 (assemble_v2_result).

### What changes for downstream stages

Nothing. Stages 4-9 consume `parsed_gen` (= `strict_result`) exactly as before.
If strict fails, `parsed_gen.parse_status == "failed"` and the pipeline skips
classification (existing behavior at line 103: `if parsed_gen.parse_status == "success"`).

---

## 9. Test Plan

### New test file: `tests/test_parser_v2_split.py`

### 9.1 Strict PASS

- Valid JSON, no fences, no extra text -> `parse_valid=True`, `schema_valid=True`, `extra_text_detected=False`
- Valid JSON wrapped in ` ```json ... ``` ` fences only -> same (fences are tolerated transport)

### 9.2 Strict FAIL -- format violations **[REV]**

- JSON with leading commentary: `"Here is the fix:\n{...}"` -> `extra_text_outside_json`
- JSON with trailing commentary: `"{...}\nLet me know if this helps!"` -> `extra_text_outside_json`
- JSON with both: `"Answer:\n{...}\nDone."` -> `extra_text_outside_json`
- Fenced JSON with surrounding text: ` "Some text\n```json\n{...}\n```\nMore text" ` -> `extra_text_outside_json` (fences stripped, but surrounding text remains)

### 9.3 Strict FAIL -- parse errors

- `""` -> `empty_response`, `parse_valid=False`
- `"just text"` -> `no_json_block`, `parse_valid=False`
- `"{bad"` -> `json_decode_error`, `parse_valid=False`
- `"[1, 2]"` -> `not_dict`, `parse_valid=False`
- Triple-quote docstring in files -> `json_decode_error`, `parse_valid=False` (strict does NOT repair)

### 9.4 Strict FAIL -- schema errors (parse succeeds, schema fails) **[REV]**

- Valid JSON missing `files` key -> `parse_valid=True`, `schema_valid=False`, `parse_status="invalid"`
- Valid JSON with `root_cause` too short -> `parse_valid=True`, `schema_valid=False`, `parse_status="partial"`

This is the key distinction: `parse_valid=True` means the model serialized correctly.
`schema_valid=False` means it used the wrong schema. Different failure modes.

### 9.5 Recovery PASS -- passthrough

- Valid JSON, clean -> `strict_equivalent=True`, `recovery_type=None`
- Verify `recovery_steps` contains only the strict-equivalent steps

### 9.6 Recovery PASS -- actual recovery

- Triple-quote case -> `recovery_type="triple_quote_fix"`, `strict_equivalent=False`
- JSON with surrounding text -> `recovery_type="strip_surrounding_text"`, `strict_equivalent=False`
- JSON findable only in raw -> `recovery_type="raw_block_extraction"`, `strict_equivalent=False`
- Each case: verify `recovery_steps` is complete and ordered

### 9.7 Recovery FAIL

- Completely unparseable -> `parse_error="recovery_failed"`, verify `recovery_steps` lists all attempted phases
- Valid JSON but missing required fields -> `parse_valid=True`, `schema_valid=False` (recovery parses but does NOT invent fields)

### 9.8 Strict/Recovery agreement **[REV]**

- For every clean valid input: `strict.parse_status == recovery.parse_status` AND `recovery.strict_equivalent == True`
- For every triple-quote input: `strict.parse_valid == False` AND `recovery.parse_valid == True` AND `recovery.strict_equivalent == False`
- **Invariant test:** For ALL inputs, if `recovery.strict_equivalent == True` then `strict.parse_status == recovery.parse_status`

### 9.9 Determinism test **[REV]**

- For each of the 6 known nano parse-failure raw responses:
  - Call `parse_generation_v2_recover` 10 times
  - Assert all 10 results are identical (same `recovery_type`, same `parse_status`, same `full_json`)

### 9.10 Regression test using real ablation data

Same as v1 plan:
- Load 6 nano parse-failure raw responses from `logs/v2_ablation_nano/2026-03-29_20-32-44_v2_ablation_nano_002/calls/`
- Assert strict fails on all 6 (`parse_valid=False`)
- Assert recovery succeeds on all 6 (`parse_valid=True`, `recovery_type="triple_quote_fix"`)
- Assert `strict_equivalent=False` on all 6
- **[REV]** Also assert `recovery_steps` contains `"triple_quote_fix"` and does NOT contain any Phase A success

### 9.11 Recovery whitelist boundary tests **[REV]**

- Input with missing `files` key: recovery MUST NOT invent it -> `schema_valid=False`
- Input with two separate JSON objects: recovery MUST NOT merge them -> extracts first only
- Input with JSON array at top level: recovery MUST NOT coerce to dict -> `not_dict`
- Input with `"code": {...}` instead of `"files": {...}`: recovery renames to `files` -> `recovery_type="code_to_files_rename"` (the one allowed field normalization)

---

## 10. Parser as Experimental Variable

The parser is not neutral infrastructure. It is part of the measurement system.

### What the parser measures

| Parser | What it captures | Analogy |
|---|---|---|
| STRICT | "Can the model produce a valid, correctly-formatted JSON response with the right schema, no extra text, on the first attempt?" | Measuring a student's exam answer as-submitted |
| RECOVERY | "If we correct obvious formatting errors, does the model's underlying reasoning and code come through?" | Grading a student's exam while ignoring spelling errors |

### The gap between them IS the finding

```
serialization_tax = recovery_parse_rate - strict_parse_rate
```

This is not a bug to fix. It is a measurement:

- **High serialization_tax** (e.g., gpt-4.1-nano at 7.5%) means the model's JSON
  formatting ability is a bottleneck. The model can reason and code correctly but
  cannot serialize its output. Structured prompting is disproportionately penalized.
- **Zero serialization_tax** (e.g., gpt-5-mini at 0%) means the model's formatting
  is not a bottleneck. Differences between conditions reflect genuine reasoning
  differences.
- **Per-condition serialization_tax** reveals whether structured prompts (LEG) impose
  higher serialization burden than baseline (they do: LEG requires 5 fields, baseline 3).

### Implications for experiment design

1. **Report both rates.** Every table should show strict AND recovery parse rates.
   The gap is itself a dependent variable.
2. **Do NOT use recovery for pass/fail decisions.** The pipeline uses strict.
   Recovery is diagnostic only.
3. **The recoverable_failure_rate per condition** tells you how much of the BL-LEG gap
   is serialization vs reasoning. For gpt-4o-mini: 9 of 22 LEG failures are parse
   failures. Without them, the BL-LEG gap shrinks from 14pp to ~6pp.

---

## 11. File Change Summary

| File | Change |
|---|---|
| `parser_v2.py` | Add 5 fields to `ParsedGenerationV2`. Add `_validate_and_build` helper. Add `parse_generation_v2_strict` (with extra-text check). Add `parse_generation_v2_recover` (6-phase cascade with step audit trail). Reduce `parse_generation_v2` to wrapper. Add `_fix_invalid_escapes` utility for Phase F. |
| `execution_v2.py` | Import strict + recover. Call both. Build `v2_parse_diagnostic` dict. Attach to ev. Pipeline uses strict only. |
| `evaluator_v2.py` | Add `v2_parse_diagnostic` to `assemble_v2_result` output. |
| `tests/test_v2_unit.py` | Existing tests unchanged (call `parse_generation_v2` which wraps strict). Some may fail due to `extra_text_outside_json` -- audit and update as needed. |
| `tests/test_parser_v2_split.py` | New file. ~25 test functions covering sections 9.1-9.11. |

No changes to `contracts_v2.py`, `reasoning_v2.py`, `metrics_v2.py`, or `mapping_v2.py`.
