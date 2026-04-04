# Parser V2 Three-Tier Design (Final)

## 1. Architecture Overview

Three parsers, three questions, one data model.

```
raw_response
    |
    +---> EXECUTION parser  ---> parsed_gen (drives pipeline stages 4-9)
    |
    +---> FORMAT parser     ---> format_diagnostic (logged, never consumed)
    |
    +---> RECOVERY parser   ---> recovery_diagnostic (logged, never consumed)
```

| Parser | Question it answers | Used by pipeline? |
|---|---|---|
| **EXECUTION** | "Can we extract a usable JSON dict from this response?" | **Yes** -- sole input to normalize, execute, classify |
| **FORMAT** | "Did the model follow the output instruction exactly?" | No -- diagnostic only |
| **RECOVERY** | "If we repair formatting, could this response have worked?" | No -- diagnostic only |

All three are called on every response. They share utilities but never call each other.

---

## 2. Data Model

```python
@dataclass
class ParsedGenerationV2:
    # --- Core fields (unchanged interface) ---
    parse_status: str               # "success" | "partial" | "invalid" | "failed"
    schema_variant: str             # "baseline_v2" | "leg_v2" | "lean_v2"
    full_json: dict | None          # parsed JSON dict, or None on failure
    files_dict: dict | None         # parsed["files"] if present and dict
    parse_error: str | None         # human-readable error string
    raw_response_text: str          # original response (logging only)
    parser_variant: str = "parser_v2_generation"
    validation_status: str = ""     # from validate_generation_fields
    validation_errors: list[str] = field(default_factory=list)

    # --- Decomposed validity (new) ---
    parse_valid: bool = False       # json.loads succeeded AND result is dict
    schema_valid: bool = False      # validate_generation_fields returned "valid"

    # --- Parser identity (new) ---
    parser_tier: str = "execution"  # "execution" | "format" | "recovery"

    # --- Format diagnostic (set by format parser only) ---
    format_valid: bool = False      # True iff format parser accepts
    format_error: str | None = None # specific format violation type

    # --- Recovery diagnostic (set by recovery parser only) ---
    recovery_type: str | None = None          # label of successful recovery, or None
    recovery_steps: list[str] = field(default_factory=list)  # ordered audit trail
    execution_equivalent: bool = True         # True iff recovery == execution result
```

### Derivation rule for parse_status

```python
if not parse_valid:
    parse_status = "failed"
elif schema_valid:
    parse_status = "success"
else:
    parse_status = validation_status  # "partial" or "invalid"
```

`parse_valid` and `schema_valid` are the primitive facts. `parse_status` is derived.
Downstream code may use either representation.

---

## 3. Execution Parser (Pipeline Primary)

### Signature

```python
def parse_v2_execution(raw: str, condition: str) -> ParsedGenerationV2
```

### What it accepts

A response is execution-parseable if a JSON dict can be unambiguously extracted from it.

### Pipeline

```
1.  If empty/whitespace -> FAIL "empty_response"
2.  cleaned = _strip_fences(raw)
3.  json_str = _find_json_block(cleaned)
4.  If json_str is None -> json_str = _find_json_block(raw)   [fence stripping may have helped or hurt]
5.  If json_str is None -> FAIL "no_json_block"
6.  MULTIPLE-JSON GUARD: scan for second JSON object after the first
        remaining = text_after_first_json_block.strip()
        if _find_json_block(remaining) is not None -> FAIL "multiple_json_objects"
7.  parsed = json.loads(json_str)
8.  If JSONDecodeError -> FAIL "json_decode_error: {detail}"
9.  If not isinstance(parsed, dict) -> FAIL "not_dict"
10. parse_valid = True
11. files_dict extraction
12. validate_generation_fields -> schema_valid, validation_status, validation_errors
13. Derive parse_status
14. Return with parser_tier="execution"
```

### What execution tolerates

- Markdown fences (stripped in step 2)
- Extra text before/after the JSON block (ignored -- the block extraction isolates JSON)
- Whitespace variation

### What execution rejects

- No JSON found
- Multiple JSON objects (ambiguity -- step 6)
- Invalid JSON (no repair)
- Non-dict JSON (arrays, scalars)

### Why this is the right primary parser

The execution parser answers: "did the model produce one unambiguous JSON dict?" It
does not care about instruction-following style (that is FORMAT's job) or serialization
artifacts (that is RECOVERY's job). It is the minimum gate for pipeline entry.

This is deliberately more permissive than the v2-plan "strict" parser, which rejected
extra text. That rejection belongs in FORMAT (diagnostic), not EXECUTION (pipeline).
Rejecting valid JSON because the model added "Here is my answer:" would conflate
format compliance with parse capability -- those are independent axes.

---

## 4. Format Parser (Instruction-Following Diagnostic)

### Signature

```python
def parse_v2_format(raw: str, condition: str) -> ParsedGenerationV2
```

### What it measures

"Did the model produce EXACTLY what the output instruction asked for?"

The output instruction says: produce a JSON object. No commentary. No fences. No
explanation. Just the JSON.

### Fence policy decision: OPTION A (fences = format violation)

Fences are a format violation. The output instruction does not say "wrap your JSON
in markdown fences." Models that add fences are deviating from the instruction, even
if the deviation is benign for parsing.

**Justification:** The format parser measures instruction-following fidelity, not
parseability. If we tolerate fences, we cannot distinguish "model followed instructions
exactly" from "model approximately followed instructions." For a research benchmark,
the distinction matters.

**Practical note:** This means format_valid will be False for many correct responses.
That is expected. The format_violation_rate metric captures how often models add
unnecessary formatting. It is a measurement, not a quality gate.

### Pipeline

```
1. If empty/whitespace -> FAIL "empty_response"
2. trimmed = raw.strip()
3. If trimmed starts with "```" -> FAIL "fenced_output"
4. json_str = _find_json_block(trimmed)
5. If json_str is None -> FAIL "no_json_block"
6. If trimmed != json_str (after both are whitespace-normalized) -> FAIL "extra_text"
7. parsed = json.loads(json_str)
8. If JSONDecodeError -> FAIL "json_decode_error"
9. If not isinstance(parsed, dict) -> FAIL "not_dict"
10. MULTIPLE-JSON GUARD (same as execution step 6) -> FAIL "multiple_json_objects"
11. format_valid = True
12. parse_valid = True
13. Schema validation
14. Return with parser_tier="format", format_valid=True
```

### What format rejects that execution accepts

| Input | Execution | Format | Format error |
|---|---|---|---|
| ````json\n{...}\n```` | PASS | FAIL | `fenced_output` |
| `"Here is the fix:\n{...}"` | PASS | FAIL | `extra_text` |
| `"{...}\nLet me know!"` | PASS | FAIL | `extra_text` |
| `{...}` (bare JSON) | PASS | PASS | -- |

---

## 5. Recovery Parser (Upper Bound Diagnostic)

### Signature

```python
def parse_v2_recovery(raw: str, condition: str) -> ParsedGenerationV2
```

### What it measures

"If we apply controlled, deterministic repairs to the raw output, can we extract a
valid JSON dict?" The gap between execution and recovery parse rates is the
serialization tax.

### Recovery Transformation Whitelist

Recovery may apply ONLY the following transformations. Each is labeled and recorded
in `recovery_steps`.

#### Category 1: TRANSPORT CLEANUP

| Label | Operation |
|---|---|
| `strip_fences` | Remove markdown code fences |
| `strip_surrounding_text` | Remove non-JSON text before/after block |
| `normalize_whitespace` | Trim leading/trailing whitespace |

#### Category 2: ESCAPE REPAIR

| Label | Operation |
|---|---|
| `triple_quote_fix` | Re-escape `"""..."""` inside JSON string values |
| `backslash_escape_fix` | Fix `\"\"\"` over-escaping pattern |
| `invalid_escape_fix` | Fix `\s`, `\1`, `\p` etc. that JSON rejects |

#### Category 3: STRUCTURAL ISOLATION

| Label | Operation |
|---|---|
| `raw_block_extraction` | `_find_json_block(raw)` when cleaned extraction failed |
| `embedded_json_extraction` | Extract JSON block from surrounding natural language |

#### Category 4: FIELD NORMALIZATION

| Label | Operation | Condition |
|---|---|---|
| `code_to_files_rename` | Rename `"code"` to `"files"` | ONLY if `"files"` absent AND `"code"` is a dict |

#### Forbidden transformations (explicit)

| Forbidden | Why |
|---|---|
| Invent missing fields | Hallucination |
| Merge multiple JSON objects | Ambiguity |
| Reconstruct from fragments | Interpretation |
| Coerce non-dict to dict | Structural fabrication |
| Guess file paths | Hallucination |
| Semantic rewriting | Non-deterministic |

### Recovery Pipeline (deterministic, ordered)

```
Phase A -- Execution-equivalent (passthrough)
    Execute the same logic as the execution parser.
    If succeeds -> return with:
        execution_equivalent = True
        recovery_type = None

Phase B -- Embedded JSON (extra text tolerated, already done by execution)
    [This phase exists conceptually but is already handled by execution's
     _find_json_block. If execution succeeded, Phase A caught it.
     If execution failed, the block was not findable -- skip to C.]

Phase C -- Raw block extraction
    json_str = _find_json_block(raw)
    json.loads(json_str)
    If succeeds -> return with:
        recovery_type = "raw_block_extraction"

Phase D -- Triple-quote repair (on cleaned text)
    repaired, did_repair = _repair_triple_quotes(_strip_fences(raw))
    If did_repair -> json.loads(repaired)
    If succeeds -> return with:
        recovery_type = "triple_quote_fix"

Phase E -- Triple-quote repair (on raw text)
    repaired, did_repair = _repair_triple_quotes(raw)
    If did_repair -> json.loads(repaired)
    If succeeds -> return with:
        recovery_type = "triple_quote_fix_raw"

Phase F -- Invalid escape repair
    Apply _fix_invalid_escapes() to cleaned text
    _find_json_block + json.loads on result
    If succeeds -> return with:
        recovery_type = "invalid_escape_fix"

Phase G -- Code-to-files rename (post any successful parse above)
    [Applied as a post-parse transform if json parsed but schema failed
     due to missing "files" and "code" key exists as dict.
     Only modifies the parsed dict, not the raw text.]

Phase H -- All recovery failed
    Return FAIL with parse_error = "recovery_failed"
```

Every phase appends its label and outcome to `recovery_steps` regardless of
success or failure. Example:

```python
["phase_a:FAIL(json_decode_error)",
 "phase_c:FAIL(no_json_block)",
 "phase_d:SUCCESS(triple_quote_fix)"]
```

### Multiple-JSON guard in recovery

Same rule as execution: if multiple JSON objects are detected, the phase FAILS.
Recovery must never choose between ambiguous candidates.

### Determinism guarantee

The pipeline is a fixed-order cascade. No randomness, no scoring, no heuristic
candidate selection. Same input always produces same output, same recovery_steps,
same recovery_type.

### Ordering bias acknowledgment

The fixed phase ordering introduces a bias: if phases D and F could both succeed,
D wins because it runs first. This is acceptable because:

1. The phases address different failure modes (triple-quote vs invalid-escape)
   that are unlikely to co-occur.
2. The bias is deterministic and documented.
3. `recovery_steps` records all attempts, so post-hoc analysis can determine
   which phases _would_ have succeeded.

---

## 6. Metric System

### Primary metrics (drive analysis)

| Metric | Formula | Meaning |
|---|---|---|
| `execution_parse_rate` | `count(exec.parse_valid) / N` | Can the model produce usable JSON? |
| `execution_pass_rate` | `count(exec.parse_status=="success" AND test_pass) / N` | End-to-end success rate |

### Format metrics (instruction-following diagnostic)

| Metric | Formula | Meaning |
|---|---|---|
| `format_valid_rate` | `count(fmt.format_valid) / N` | Perfect instruction following |
| `format_violation_rate` | `execution_parse_rate - format_valid_rate` | Parseable but not perfectly formatted |
| `fence_rate` | `count(fmt.format_error=="fenced_output") / N` | How often models add fences |

### Schema metrics (contract compliance)

| Metric | Formula | Meaning |
|---|---|---|
| `schema_valid_rate` | `count(exec.schema_valid) / count(exec.parse_valid)` | Schema compliance among parseable |
| `schema_violation_rate` | `count(exec.parse_valid AND NOT exec.schema_valid) / N` | Valid JSON, wrong schema |

### Recovery metrics (serialization tax)

| Metric | Formula | Meaning |
|---|---|---|
| `recovery_parse_rate` | `count(rec.parse_valid) / N` | Upper bound after repair |
| `recoverable_failure_rate` | `count(NOT exec.parse_valid AND rec.parse_valid) / N` | Lost to formatting |
| `serialization_tax` | `recovery_parse_rate - execution_parse_rate` | Performance gap from formatting |
| `recovery_type_distribution` | `Counter(rec.recovery_type)` | Which repairs are needed |

### Interpretation constraint

`execution_pass_rate` is NOT pure model reasoning capability. It is:

```
execution_pass_rate = P(parse_valid) * P(schema_valid | parse_valid) * P(test_pass | schema_valid)
```

This decomposition is REQUIRED in any reporting. The three factors measure:

1. **P(parse_valid):** JSON serialization capability
2. **P(schema_valid | parse_valid):** Instruction schema compliance
3. **P(test_pass | schema_valid):** Reasoning + code generation quality

Only factor 3 reflects genuine model reasoning. Factors 1 and 2 are formatting
overhead that varies by model and by condition (structured prompts demand more
complex JSON, increasing the formatting burden).

To isolate reasoning quality:

```
reasoning_quality_estimate = execution_pass_rate / (execution_parse_rate * schema_valid_rate)
```

Or equivalently: `P(test_pass | schema_valid)` computed directly from the data.

---

## 7. Integration Plan

### execution_v2.py (line 82, single change site)

```python
from parser_v2 import parse_v2_execution, parse_v2_format, parse_v2_recovery

# STAGE 3: Parse (all three tiers, only execution drives pipeline)
exec_result = parse_v2_execution(raw_response, condition)
format_result = parse_v2_format(raw_response, condition)
recovery_result = parse_v2_recovery(raw_response, condition)

parsed_gen = exec_result  # <-- ONLY this enters stages 4-9
```

### Diagnostic dict (attached to ev in stage 8)

```python
ev["v2_parse_tiers"] = {
    # Execution (primary)
    "exec_parse_valid": exec_result.parse_valid,
    "exec_schema_valid": exec_result.schema_valid,
    "exec_parse_error": exec_result.parse_error,
    # Format (diagnostic)
    "format_valid": format_result.format_valid,
    "format_error": format_result.format_error,
    # Recovery (diagnostic)
    "recovery_parse_valid": recovery_result.parse_valid,
    "recovery_schema_valid": recovery_result.schema_valid,
    "recovery_type": recovery_result.recovery_type,
    "recovery_steps": recovery_result.recovery_steps,
    "execution_equivalent": recovery_result.execution_equivalent,
    # Derived
    "recoverable": not exec_result.parse_valid and recovery_result.parse_valid,
}
```

### Legacy wrapper

```python
def parse_generation_v2(raw: str, condition: str) -> ParsedGenerationV2:
    """Legacy wrapper. Delegates to execution parser."""
    return parse_v2_execution(raw, condition)
```

Existing callers (`tests/test_v2_unit.py`, `execution_v2.py` pre-refactor) continue
to work. The legacy wrapper ensures the execution parser is the default.

### Isolation guarantee

The format and recovery parsers write to their own `ParsedGenerationV2` instances.
These instances are NEVER assigned to `parsed_gen`. They are ONLY accessed to
build the `v2_parse_tiers` diagnostic dict. No field from format or recovery
is read by stages 4-9 (normalize, execute, classify, metrics, assemble, log).

---

## 8. Test Plan

### File: `tests/test_parser_v2_tiers.py`

### 8.1 Execution parser

**PASS cases:**
- Bare valid JSON dict -> `parse_valid=True, schema_valid=True`
- Fenced JSON -> `parse_valid=True` (fences stripped)
- JSON with leading/trailing commentary -> `parse_valid=True` (block extracted)

**FAIL cases:**
- Empty string -> `parse_error="empty_response"`
- No JSON at all -> `parse_error="no_json_block"`
- Invalid JSON -> `parse_error` starts with `"json_decode_error"`
- JSON array -> `parse_error="not_dict"`
- Two JSON objects -> `parse_error="multiple_json_objects"`
- Triple-quote docstring -> `parse_error` starts with `"json_decode_error"` (no repair)

**Schema separation:**
- Valid JSON missing `files` -> `parse_valid=True, schema_valid=False, parse_status="invalid"`
- Valid JSON with short `root_cause` -> `parse_valid=True, schema_valid=False, parse_status="partial"`

### 8.2 Format parser

**PASS cases:**
- Bare valid JSON dict, no fences, no extra text -> `format_valid=True`

**FAIL cases:**
- Fenced JSON -> `format_valid=False, format_error="fenced_output"`
- JSON with leading text -> `format_valid=False, format_error="extra_text"`
- JSON with trailing text -> `format_valid=False, format_error="extra_text"`
- Two JSON objects -> `format_valid=False, format_error="multiple_json_objects"`
- Everything that execution rejects (empty, no JSON, invalid JSON, etc.)

### 8.3 Recovery parser

**Passthrough cases:**
- Valid clean JSON -> `execution_equivalent=True, recovery_type=None`
- Verify recovery_steps matches execution path

**Recovery cases:**
- Triple-quote (6 real nano cases) -> `recovery_type="triple_quote_fix", execution_equivalent=False`
- JSON in raw but not cleaned -> `recovery_type="raw_block_extraction"`
- Invalid Python escapes in JSON -> `recovery_type="invalid_escape_fix"`

**Rejection cases:**
- Completely unparseable -> `parse_error="recovery_failed"`
- Missing required fields -> `parse_valid=True, schema_valid=False` (recovery does NOT invent)
- Two JSON objects -> FAIL (recovery does NOT merge)
- JSON array -> FAIL (recovery does NOT coerce)

### 8.4 Cross-tier agreement

- For bare valid JSON: all three tiers return `parse_valid=True, schema_valid=True`
- For fenced valid JSON: execution PASS, format FAIL (fenced_output), recovery PASS (passthrough)
- For triple-quote case: execution FAIL, format FAIL, recovery PASS
- Invariant: if `recovery.execution_equivalent == True` then
  `execution.parse_status == recovery.parse_status`

### 8.5 Multiple-JSON guard (all tiers)

- Input: `'{"a":1}\n{"b":2}'`
- Execution: FAIL `multiple_json_objects`
- Format: FAIL `multiple_json_objects`
- Recovery: FAIL `multiple_json_objects`

### 8.6 Determinism

- For each of 6 known nano parse-failure raw responses:
  - Call `parse_v2_recovery` 10 times
  - Assert all 10 produce identical `recovery_type`, `parse_status`, `full_json`, `recovery_steps`

### 8.7 Regression (real ablation data)

- Load 6 nano parse-failure responses from
  `logs/v2_ablation_nano/2026-03-29_20-32-44_v2_ablation_nano_002/calls/`
- Cases: `partial_update_b/leg_reduction_v2`, `stale_cache_b/leg_reduction_v2`,
  `mutable_default_a/leg_reduction_lean_v2`, `mutable_default_b/baseline_v2`,
  `effect_order_b/leg_reduction_v2`, `retry_dup_c/leg_reduction_v2`
- Assert execution FAILS on all 6
- Assert format FAILS on all 6
- Assert recovery PASSES on all 6 with `recovery_type="triple_quote_fix"`
- Assert `execution_equivalent=False` on all 6

### 8.8 Whitelist boundary

- Missing `files` key: recovery MUST NOT invent it
- `"code": {...}` instead of `"files"`: recovery renames -> `recovery_type="code_to_files_rename"`
- JSON fragments (half-object): recovery MUST NOT reconstruct
- Two valid JSON dicts: recovery MUST NOT merge or pick

---

## 9. Parser as Experimental Variable

### The three tiers decompose the measurement

| Tier | Measures | Analogous to |
|---|---|---|
| FORMAT | "Did the model follow instructions precisely?" | Exam: answer written in the required format |
| EXECUTION | "Can we use the output, tolerating minor deviations?" | Exam: answer readable despite formatting |
| RECOVERY | "Could the output have worked with formatting help?" | Exam: answer recoverable from messy handwriting |

### The gaps between tiers ARE findings

```
format_gap      = execution_parse_rate - format_valid_rate    (format violations that don't affect parsing)
serialization_tax = recovery_parse_rate - execution_parse_rate  (formatting errors that block parsing)
```

From the v2 ablation data:

| Model | execution_parse_rate | est. format_valid_rate | est. recovery_parse_rate | serialization_tax |
|---|---|---|---|---|
| gpt-4.1-nano (old parser) | ~87% | (unknown, not measured) | ~95% | ~8% |
| gpt-4.1-nano (fixed parser) | ~95% | (unknown) | ~98% | ~3% |
| gpt-4o-mini | ~92% | (unknown) | ~97% | ~5% |
| gpt-5-mini | ~100% | (unknown) | ~100% | 0% |

The three-tier design makes these gaps first-class measurements rather than
implementation artifacts.

### Per-condition interaction

Structured prompts (LEG) require 5-field JSON; baseline requires 3-field JSON.
The serialization tax is condition-dependent:

```
serialization_tax(LEG) > serialization_tax(baseline)
```

This means part of the observed BL-LEG pass rate gap is formatting overhead, not
reasoning quality difference. The probabilistic decomposition (section 6) allows
isolating the reasoning component:

```
P(test_pass | schema_valid) for LEG vs baseline
```

If this factor is equal, the entire BL-LEG gap is serialization. If LEG is lower,
the structured prompt genuinely degrades reasoning-to-code translation.

---

## 10. File Change Summary

| File | Change |
|---|---|
| `parser_v2.py` | Add fields to `ParsedGenerationV2`. Add `_validate_and_build` shared helper. Add `_count_json_objects` for multiple-JSON guard. Add `_fix_invalid_escapes` for Phase F. Add `parse_v2_execution`, `parse_v2_format`, `parse_v2_recovery`. Keep `parse_generation_v2` as legacy wrapper to execution. |
| `execution_v2.py` | Import all three parsers. Call all three. Build `v2_parse_tiers` diagnostic. Pipeline uses execution only. |
| `evaluator_v2.py` | Include `v2_parse_tiers` in `assemble_v2_result`. |
| `tests/test_v2_unit.py` | Unchanged (calls `parse_generation_v2` which wraps execution). |
| `tests/test_parser_v2_tiers.py` | New. ~30 test functions covering sections 8.1-8.8. |

No changes to `contracts_v2.py`, `reasoning_v2.py`, `metrics_v2.py`, `mapping_v2.py`.
