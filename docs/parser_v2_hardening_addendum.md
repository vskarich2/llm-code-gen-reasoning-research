# Parser V2 Three-Tier Design: Hardening Addendum

This addendum corrects 10 specific weaknesses in the three-tier design. It does
not restate the base design. Read `parser_v2_three_tier_design.md` first.

---

## H1. Formal Specification of `_find_json_block`

This function is the extraction primitive used by all three parsers. Its behavior
defines ground truth for "what JSON did the model produce."

### Algorithm

```
_find_json_block(text: str) -> (json_str: str | None, end_pos: int)
```

Returns the first balanced top-level `{ ... }` block and the position immediately
after it. Returns `(None, -1)` if no block found.

```
1. Scan text left-to-right for first '{' character not inside a JSON string.
   If none found -> return (None, -1).
   Record start_pos.

2. Initialize:
   depth = 0
   in_string = False
   escape_next = False

3. For each character at position i from start_pos to end of text:

   a. If escape_next:
      escape_next = False
      continue

   b. If in_string:
      If char == '\\':
         escape_next = True
         continue
      If char == '"':
         in_string = False
      continue  [all other chars inside strings are ignored]

   c. If not in_string:
      If char == '"':
         in_string = True
         continue
      If char == '{':
         depth += 1
      If char == '}':
         depth -= 1
         If depth == 0:
            return (text[start_pos : i+1], i+1)

4. If loop exhausts without depth reaching 0 -> return (None, -1)
```

### Properties

- **Deterministic:** Same input always produces same output.
- **First-match:** Returns the FIRST top-level `{...}` block. If the text contains
  `{...} junk {...}`, the first block is returned. The second is detected by the
  multiple-JSON guard (section H7).
- **String-aware:** Braces inside JSON string values (`"key": "value with { braces }"`)
  do not affect depth tracking.
- **Escape-aware:** `\"` inside strings does not toggle string state.
- **No heuristics:** No scoring, no candidate ranking, no regex. Pure stack-based parsing.

### Signature change

The current implementation returns `str | None`. The revised implementation returns
`tuple[str | None, int]` to support the multiple-JSON guard (which needs `end_pos`
to scan for a second block).

### Edge cases

| Input | Result | Reason |
|---|---|---|
| `""` | `(None, -1)` | No `{` found |
| `"just text"` | `(None, -1)` | No `{` found |
| `"{"` | `(None, -1)` | Unbalanced -- depth never returns to 0 |
| `"{}"` | `("{}", 2)` | Minimal valid block |
| `"text { } text"` | `("{ }", 8)` | First block extracted, surrounding text ignored |
| `'{"a": "}"}'` | `('{"a": "}"}', 12)` | Brace inside string ignored |
| `'{"a": 1}\n{"b": 2}'` | `('{"a": 1}', 9)` | First block only; second detected by guard |

---

## H2. Mis-extraction Signal

### Problem

When `parse_valid == True` but `schema_valid == False`, two explanations exist:

1. The model produced the right JSON but with schema errors (e.g., missing `files`).
2. `_find_json_block` extracted the WRONG JSON object (e.g., model output contained
   a JSON example in its explanation, and that example was extracted instead of the
   intended response).

These are different failure modes. Case 2 is an extraction error, not a model error.

### New field

```python
possible_mis_extraction: bool = False
```

Set `True` when ALL of the following hold:
- `parse_valid == True`
- `schema_valid == False`
- At least one required top-level key from the schema is missing entirely

Rationale: If the JSON parses correctly but is missing `root_cause` AND `files`,
the extracted block is almost certainly not the model's intended output. It may be
a JSON example embedded in the model's explanation.

If only one field has wrong type/length but all keys are present, this is more
likely a genuine schema error (model produced the right structure but with bad values),
so `possible_mis_extraction = False`.

### Detection rule

```python
required_keys = SCHEMA_REQUIRED_FIELDS[schema_variant]
present_keys = set(full_json.keys()) & required_keys
missing_keys = required_keys - present_keys

possible_mis_extraction = (
    parse_valid
    and not schema_valid
    and len(missing_keys) >= 2  # multiple required keys absent
)
```

### Metric

```
mis_extraction_rate = count(possible_mis_extraction) / N
```

High `mis_extraction_rate` indicates the extraction primitive is selecting wrong
blocks -- a systemic problem requiring investigation.

---

## H3. Execution-Recovery Equivalence (Formalized)

### Definition

```python
execution_equivalent = (
    exec_result.parse_valid == True
    and recovery_result.parse_valid == True
    and exec_result.full_json == recovery_result.full_json
)
```

This is a **structural equality check** on the parsed dicts. Not fuzzy. Not approximate.
`==` on Python dicts is recursive value equality.

### Where it is computed

In `execution_v2.py`, AFTER both parsers have returned:

```python
execution_equivalent = (
    exec_result.parse_valid
    and recovery_result.parse_valid
    and exec_result.full_json == recovery_result.full_json
)
recovery_result.execution_equivalent = execution_equivalent
```

The recovery parser itself sets `execution_equivalent` provisionally in Phase A
(passthrough). The integration code overrides it with the definitive comparison.

### Why not inside recovery?

Recovery does not have access to the execution result. The equivalence check
requires both outputs. It is therefore computed at the call site (execution_v2.py),
not inside the parser.

---

## H4. Execution-Subset-of-Recovery Invariant

### Statement

```
INVARIANT: If execution.parse_valid == True, then recovery.parse_valid MUST be True.
```

Recovery is a superset of execution. Anything execution can parse, recovery can
also parse (via Phase A passthrough). If this invariant is violated, there is a
bug in the recovery parser.

### Enforcement

```python
if exec_result.parse_valid and not recovery_result.parse_valid:
    _log.error(
        "INVARIANT VIOLATION: execution parsed but recovery failed. "
        "case=%s condition=%s exec_error=%s recovery_error=%s",
        cid, condition, exec_result.parse_error, recovery_result.parse_error,
    )
    invariant_violations += 1
```

This is logged as an error, not a crash. The pipeline continues using the execution
result. The violation count is tracked in the diagnostic dict:

```python
ev["v2_parse_tiers"]["invariant_violation"] = not (
    not exec_result.parse_valid or recovery_result.parse_valid
)
```

### Metric

```
invariant_violation_count = count(exec.parse_valid AND NOT rec.parse_valid)
```

Expected value: 0. Any non-zero value is a parser bug.

---

## H5. Schema Validation Specification

This section formally documents what `validate_generation_fields` checks, as
implemented in `contracts_v2.py:53-91`.

### Schema definitions

**baseline_v2** (3 required fields):

| Field | Type | Constraint |
|---|---|---|
| `root_cause` | `str` | `len(strip()) >= 10` |
| `fix_strategy` | `str` | `len(strip()) >= 10` |
| `files` | `dict` | Non-empty (`len >= 1`) |

**leg_v2** and **lean_v2** (5 required fields):

| Field | Type | Constraint |
|---|---|---|
| `root_cause` | `str` | `len(strip()) >= 10` |
| `fix_strategy` | `str` | `len(strip()) >= 10` |
| `code_commitments` | `list` or `str` | If list: non-empty. If str: accepted as-is. |
| `risk_check` | `str` | Non-empty after strip. `"SAFE"` is valid for lean_v2. |
| `files` | `dict` | Non-empty (`len >= 1`) |

### Validation outcomes

| Outcome | validation_status | Trigger |
|---|---|---|
| All fields present, correct type, meet constraints | `"valid"` | No errors |
| All fields present but some have wrong type/length | `"partial"` | Errors but none are "missing required" |
| One or more required fields entirely absent | `"invalid"` | At least one "missing required field" error |

### Mapping to data model

```
schema_valid = (validation_status == "valid")
```

`"partial"` maps to `schema_valid = False`. A field that exists but is too short
(e.g., `root_cause: "bug"`) is a schema violation, not a parse failure.

### Extra fields

Extra fields not in the required set are IGNORED by validation. They are preserved
in `full_json` but do not affect `schema_valid`.

---

## H6. Schema Normalization Tracking

### Problem

Recovery Phase G (`code_to_files_rename`) modifies the parsed dict after JSON parsing.
This is a schema-level transformation, not a formatting repair. It must be tracked
separately from formatting recoveries.

### New field

```python
schema_normalization_applied: bool = False
```

Set `True` ONLY when recovery modifies the parsed dict's keys or structure (currently
only `code_to_files_rename`). Set `False` for all formatting-only recoveries
(triple_quote_fix, raw_block_extraction, etc.).

### Metric

```
schema_normalization_rate = count(recovery.schema_normalization_applied) / N
```

### Reporting distinction

Two categories of recovery success:

1. **Format recovery** (`schema_normalization_applied == False`): The model's JSON
   content was correct; only the serialization was broken. The recovered dict is
   semantically identical to what the model intended.

2. **Schema recovery** (`schema_normalization_applied == True`): The model's JSON
   structure deviated from the contract. Recovery re-mapped keys. The recovered dict
   may not reflect the model's exact intent.

These should be reported separately. `native_schema_valid_rate` (schema valid without
normalization) is the true measurement of schema compliance.

---

## H7. Multiple-JSON Detection Specification

### Algorithm

Uses `_find_json_block` (revised to return `end_pos`):

```python
def _count_json_objects(text: str) -> int:
    """Count top-level JSON objects in text."""
    count = 0
    pos = 0
    while pos < len(text):
        block, end_pos = _find_json_block(text[pos:])
        if block is None:
            break
        count += 1
        pos += end_pos
    return count
```

### Rules

- Called on the SAME text that `_find_json_block` operates on (after fence stripping
  for execution/format, on raw for recovery Phase C).
- If count > 1: the parser FAILS with `"multiple_json_objects"`.
- This applies to ALL three tiers identically.

### Why this matters

If the model outputs:

```
Here is the root cause analysis:
{"analysis": "the bug is in create_config"}
And here is the fix:
{"root_cause": "aliasing", "fix_strategy": "copy", "files": {"a.py": "..."}}
```

Without the guard, `_find_json_block` would extract the FIRST block (`{"analysis": ...}`),
which is wrong. The guard detects two blocks and fails, forcing the response to be
classified as `multiple_json_objects` rather than silently mis-extracting.

### Edge case: nested JSON

A single JSON object containing nested objects (`{"files": {"a.py": "..."}}`) is
ONE top-level block. The nested `{...}` is inside the outer block and does not
trigger the guard. `_find_json_block` handles this via depth tracking.

---

## H8. Recovery Semantic Preservation Guarantee

### Definition

A recovery transformation is **semantically preserving** if the `full_json` dict
produced by recovery, when both parse and recover succeed, represents the same
logical content as what the model intended.

### Boundary between formatting and semantic

| Transformation | Category | Preserves semantics? | Justification |
|---|---|---|---|
| Strip fences | Formatting | Yes | Fences are transport, not content |
| Strip surrounding text | Formatting | Yes | JSON content unchanged |
| Fix triple-quote escaping | Formatting | Yes | File content is identical; only JSON encoding changes |
| Fix invalid escapes | Formatting | Yes | String content is identical; only escape sequences fixed |
| Raw block extraction | Formatting | Yes | Same JSON, different extraction path |
| `code` -> `files` rename | **Schema** | **Possibly not** | Model may have used `"code"` intentionally |

The `code_to_files_rename` transformation is the ONLY one that crosses the
formatting/semantic boundary. It is flagged via `schema_normalization_applied`
and must be reported separately.

### Forbidden boundary crossings

Recovery MUST NOT:

- Change dictionary values (only keys, and only `code` -> `files`)
- Reorder or restructure nested data
- Infer missing values from context
- Normalize string content (e.g., strip whitespace from code)

These would alter the model's output semantics and invalidate downstream evaluation.

---

## H9. Extended Metrics

### New metrics (added to section 6 of base design)

| Metric | Formula | Meaning |
|---|---|---|
| `mis_extraction_rate` | `count(exec.possible_mis_extraction) / N` | Extraction selected wrong JSON block |
| `schema_normalization_rate` | `count(rec.schema_normalization_applied) / N` | Recovery needed schema-level change |
| `native_schema_valid_rate` | `count(exec.schema_valid) / count(exec.parse_valid)` | Schema compliance without normalization |
| `normalized_schema_valid_rate` | `count(rec.schema_valid) / count(rec.parse_valid)` | Schema compliance with normalization allowed |
| `invariant_violation_count` | `count(exec.parse_valid AND NOT rec.parse_valid)` | Parser bug indicator (expected: 0) |

### All metrics include numerator and denominator

Every metric logged to the diagnostic dict must include raw counts, not just rates:

```python
ev["v2_parse_metrics"] = {
    "n_total": total,
    "n_exec_parse_valid": exec_parse_count,
    "n_exec_schema_valid": exec_schema_count,
    "n_format_valid": format_valid_count,
    "n_recovery_parse_valid": recovery_parse_count,
    "n_recoverable": recoverable_count,
    "n_mis_extraction": mis_extraction_count,
    "n_schema_normalized": schema_norm_count,
    "n_invariant_violations": invariant_violation_count,
}
```

These are per-run aggregates, not per-event. They are computed at the end of the
run and written to `metadata.json` or a dedicated `parse_metrics.json`.

---

## H10. Explicit Limitations

### Assumption: single intended JSON object

The parser assumes the model's intended output is a single top-level JSON object.
If the model produces its answer as two separate JSON objects (e.g., reasoning
in one, code in another), the multiple-JSON guard will reject it as ambiguous.
This is a design choice, not a bug: the prompt instruction says "produce a JSON
object" (singular).

### Extraction may select wrong block

If the model embeds a JSON example in its explanation BEFORE the actual answer,
`_find_json_block` will extract the example, not the answer. The `possible_mis_extraction`
signal flags this but does not correct it. In future work, a heuristic that selects
the block containing expected keys could improve accuracy, but this introduces
non-determinism and is explicitly out of scope for this design.

### Recovery bounds parseability, not correctness

A response that recovery successfully parses may still contain:
- Wrong code
- Incorrect reasoning
- Misidentified root cause

Recovery only guarantees the output is well-formed JSON matching the schema contract.
It says nothing about the semantic quality of the content. The `recovery_parse_rate`
is an upper bound on "could have been evaluated," not "would have been correct."

### Non-determinism at temperature=0.0

Empirical observation from the v2 ablation: 50 case/condition pairs changed between
two gpt-4.1-nano runs at temperature=0.0. This means the raw model output is not
fully deterministic, even when the parser is. Parser metrics should be interpreted
with this noise floor in mind. Single-trial differences of less than ~5% may be
within infrastructure variation.

---

## Updated Data Model (consolidated)

All new fields from this addendum:

```python
@dataclass
class ParsedGenerationV2:
    # [existing fields unchanged -- see base design]

    # --- H2: Mis-extraction signal ---
    possible_mis_extraction: bool = False

    # --- H6: Schema normalization ---
    schema_normalization_applied: bool = False
```

The `execution_equivalent` field (H3) is already in the base design but its
computation is moved to the call site (execution_v2.py) rather than inside the
recovery parser. The field remains on the dataclass; its value is set after both
parsers return.

---

## Updated Test Plan (additions to base design section 8)

### H-Tests: Hardening-specific

**H1-test: _find_json_block edge cases**
- `""` -> `(None, -1)`
- `"no braces"` -> `(None, -1)`
- `"{"` -> `(None, -1)` (unbalanced)
- `"{}"` -> `("{}", 2)`
- `'{"a": "}"}'` -> correctly handles brace in string
- `'{"a": 1} {"b": 2}'` -> returns first, end_pos points to space before second

**H2-test: Mis-extraction detection**
- JSON with all required keys -> `possible_mis_extraction = False`
- JSON with 1 required key missing but others present -> `possible_mis_extraction = False`
- JSON with 2+ required keys missing -> `possible_mis_extraction = True`
- JSON with all keys present but wrong types -> `possible_mis_extraction = False`

**H4-test: Execution-subset-of-recovery invariant**
- For every test input: if execution PASSES, assert recovery also PASSES
- Construct a synthetic input where this might fail (there should be none)

**H7-test: Multiple-JSON guard**
- `'{"a":1}\n{"b":2}'` -> count=2, all tiers FAIL
- `'{"a":{"b":1}}'` -> count=1, passes (nested is not multiple)
- `'text {"a":1} text'` -> count=1, passes
- `'{"a":1}, {"b":2}'` -> count=2, FAIL (comma-separated objects)

**H8-test: Semantic preservation**
- For each recovery type that succeeds on real data: verify
  `recovery.full_json` content matches what a human would extract
- For `code_to_files_rename`: verify `schema_normalization_applied = True`
- For all other recoveries: verify `schema_normalization_applied = False`
