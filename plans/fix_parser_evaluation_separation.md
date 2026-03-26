# Plan: Separate Code Execution from Metadata Validation

**Version:** v1
**Date:** 2026-03-26
**Status:** Plan only. No code changes.
**Scope:** leg_reduction.py, execution.py, parse.py, reconstructor.py

---

## 1. Root Cause Model

### Current Pipeline

```
model_output
  │
  ├─ Standard conditions: parse_model_response() ──────────────────┐
  │    7-tier fallback: file_dict → code_dict → JSON → lenient     │
  │    → substring → code_block → raw_fallback                     │
  │    Result: {code, reasoning, parse_error, files}               │
  │                                                                 │
  ├─ LEG-reduction: parse_leg_reduction_output() ──────────────────┤
  │    1. Extract JSON                                              │
  │    2. Validate 6 top-level required fields                      │
  │    3. Type-check all fields                                     │
  │    4. Validate revision_history metadata structure              │
  │    5. Validate cross-field consistency                          │
  │    Result: {code, valid, parse_error, validation_errors}        │
  │                                                                 │
  ├─ Retry harness: parse_structured_output() ─────────────────────┤
  │    Requires: reasoning, plan, code                              │
  │    If fail → fallback to parse_model_response()                 │
  │    Result: {code, reasoning, plan, valid_schema, parse_error}   │
  │                                                                 │
  ├─ V2 file-dict: reconstruct_strict() ───────────────────────────┤
  │    Requires: all manifest files present                         │
  │    If missing file → status=FAILED_MISSING_FILES                │
  │    If syntax error → status=FAILED_SYNTAX_ERRORS                │
  │                                                                 │
  ▼                                                                 │
  parsed = {code, reasoning, parse_error, _raw_fallback}      ◄────┘
  │
  ▼
  evaluate_output(case, parsed)
  │
  ├─ exec_evaluate(case, parsed["code"])  ← code execution (behavioral)
  │    → pass/fail based on invariant tests
  │
  ├─ llm_classify(case, code, reasoning, parse_error=...)
  │    → PARSE GATE: if parse_error + empty reasoning → None
  │    → else: classifier runs
  │
  └─ result = {pass, score, reasoning_correct, ...}
```

### Where Valid Code Is Currently Dropped

**Failure Point 1 — LEG-reduction metadata validation (82% of failures)**

`parse_leg_reduction_output()` extracts `code` from the JSON at line 505, but sets `parse_error` at line 512 when ANY metadata validation error exists. Metadata errors include:

- `changes_made[0]` missing `target` sub-field (incidental metadata)
- `internal_revisions` count mismatch with `revision_history` length (counting convention)
- `verification` array length mismatch with last revision (consistency check)
- `changes_made` not null for revision 0 (schema convention)

These are all metadata schema violations. None of them indicate the code is wrong or absent. But `parse_error` being set cascades:

- `execution.py:488` propagates `parse_error` to `parsed["parse_error"]`
- The parse gate (Fix D) sees non-empty reasoning + parse_error → classifies as `MALFORMED_BUT_RECOVERED` (reasoning still reaches classifier — this is CORRECT)
- BUT: `ev["leg_reduction"]["valid_schema"] = lr_parsed["valid"]` is False, which downstream analysis uses to filter or discount results
- AND: the `parse_error` string appears in dashboards and metrics as if code extraction failed

**The core defect**: `valid` and `parse_error` conflate two independent signals:
1. Did we extract usable code? (YES in 9/11 cases)
2. Did the metadata conform to the strict LEG schema? (NO in 9/11 cases)

**Failure Point 2 — Reconstructor strict mode (V2 file-dict)**

`reconstruct_strict()` returns `FAILED_MISSING_FILES` when a model uses a slightly different file path (e.g., omits a subdirectory prefix). The code exists in the response but is keyed under the wrong path. `execution.py:225` then sets `_reconstruction_error=True` and the code path falls through to the standard parse_model_response() fallback — which extracts the code LESS precisely because it doesn't have file-path awareness.

**Failure Point 3 — parse_structured_output() strict schema (retry harness)**

`parse_structured_output()` requires `reasoning`, `plan`, `code` — all three. If `plan` is missing or is a string instead of a list, the entire parse fails with `parse_error="missing_key: plan"`. The code and reasoning exist in the JSON but are not extracted. The fallback to `parse_model_response()` may or may not recover them.

### Diagram: Where Code Is Present But Dropped

```
MODEL OUTPUT (valid JSON, correct code inside)
  │
  ▼
PARSER: "changes_made[0] missing 'target' field"
  │
  ▼
parse_error = "validation_errors(3): revision_history[1].changes_made[0]: missing 'target'; ..."
valid = False
code = "def create_config():\n    return dict(DEFAULTS)"   ← CODE IS HERE
  │
  ▼
DOWNSTREAM: sees parse_error → logs as parse failure
            sees valid=False → marks schema_valid=False
            BUT: code IS passed to exec_evaluate
            AND: exec_evaluate DOES run the code
            AND: code PASSES the invariant test

RESULT: pass=True, but parse_error is set, valid=False
        → Metrics count this as "parse failure" even though code was correct
        → Dashboard shows elevated parse error rate for LEG condition
        → Cross-model comparison is contaminated
```

---

## 2. Failure Type Separation

### The Three Independent Signals

| Signal | Question | Source | Authority |
|---|---|---|---|
| **A. Execution Correctness** | Did the code pass invariant tests? | `exec_evaluate()` | SOLE authority for code correctness. Unrelated to output format. |
| **B. Schema Compliance** | Did the output match the required LEG/retry/file-dict structure? | `parse_leg_reduction_output()`, `parse_structured_output()`, `reconstruct_strict()` | Research signal about model's instruction-following. NOT a gate on execution. |
| **C. Code Extraction** | Was code successfully extracted from the output? | Parser tier that found the code | Gate on execution: if no code extracted, execution cannot proceed. |

### Current Conflation

Currently, `parse_error` and `valid` conflate all three:

- `parse_error` is set for B (schema violations) even when C (code extraction) succeeded
- `valid=False` for B (metadata mismatch) even when A (code passes tests)
- A model that produces correct code but formats metadata wrong gets the same `parse_error` as a model that produced garbage

### Required Separation

After the fix, each case must have THREE independent fields:

```json
{
  "code_extracted": true,          // C: was code found in the output?
  "code_execution_pass": true,     // A: did the code pass tests?
  "schema_compliant": false,       // B: did metadata match required schema?
  "schema_violations": ["..."],    // B: list of specific violations
  "parse_error": null              // only set for C failures (no code extractable)
}
```

**Critical rule**: `parse_error` is set ONLY when code extraction (C) fails — meaning no code could be found in the model output at all. Schema violations (B) are recorded separately in `schema_violations` and `schema_compliant`, and NEVER set `parse_error`.

---

## 3. New Evaluation Contract

### Rule

> Code execution MUST NOT depend on metadata schema compliance.

### Specification

1. **Code extraction is the gating criterion, not schema compliance.** If the parser extracts a non-empty `code` field from the model output, `exec_evaluate()` runs. Period. It does not matter whether `changes_made[0]` has a `target` field, or whether `internal_revisions` matches `len(revision_history)`.

2. **Execution proceeds when**: `code` is non-empty AND `code` has >= 10 characters (existing threshold in `exec_evaluate`).

3. **Execution is blocked when**: `code` is empty, None, or < 10 characters. This is a TRUE parse failure — no code was extractable.

4. **Hard failures** (execution blocked):
   - Empty model response
   - No JSON found in output (Category B from the analysis: 18% of failures)
   - JSON found but `code` field is absent or empty
   - JSON found but `code` field is not a string

5. **Soft failures** (execution proceeds, schema_compliant=False):
   - Missing metadata sub-fields (`changes_made[].target`, etc.)
   - Count mismatches (`internal_revisions` vs `revision_history` length)
   - Consistency mismatches (top-level verification vs last revision verification)
   - Missing optional metadata fields (`verification`, `invariants_checked`)
   - Extra fields in the output (model added fields not in schema)

### Application to Each Parser

**LEG-reduction (`parse_leg_reduction_output`)**:
- Top-level `code` field present and non-empty string → code_extracted=True, parse_error=None
- Metadata validation errors → schema_compliant=False, schema_violations=[...], BUT parse_error stays None
- `code` absent or empty → code_extracted=False, parse_error="missing_required_field: code"

**Retry harness (`parse_structured_output`)**:
- `code` field present and non-empty string → code_extracted=True
- `plan` missing or wrong type → schema_compliant=False (plan is metadata, not code)
- `reasoning` missing → reasoning_extracted=False (separate from code extraction)

**Reconstructor (`reconstruct_strict`)**:
- Any model file contains non-empty code → code_extracted=True
- Missing files → schema_compliant=False (model omitted expected files)
- Extra files → schema_compliant=False (model added unexpected files)
- AST syntax error in model file → code_extracted=True (execution will catch the syntax error)

---

## 4. Parser Redesign Strategy

### 4.1 LEG-Reduction Parser: Split Validation from Extraction

**Current**: `parse_leg_reduction_output()` is a single function that does JSON extraction, code extraction, AND metadata validation. If any metadata validation fails, it sets `parse_error` and `valid=False`.

**New design**: Split into two phases:

**Phase 1 — Code Extraction (always runs)**:
1. Extract JSON from raw text
2. If JSON extraction fails → hard failure (parse_error set, code_extracted=False)
3. Extract `code` field from parsed JSON
4. If `code` absent or empty → hard failure
5. Extract `bug_diagnosis` (reasoning) if present
6. Return: `{code, bug_diagnosis, code_extracted=True, parse_error=None}`

**Phase 2 — Metadata Validation (informational, never blocks execution)**:
1. Validate `plan_steps` structure
2. Validate `revision_history` structure (all sub-fields)
3. Validate consistency checks (counts, cross-references)
4. Return: `{schema_compliant, schema_violations, validity_score}`

These two phases produce INDEPENDENT outputs. Phase 1 failure blocks execution. Phase 2 failure is recorded but does NOT block execution and does NOT set `parse_error`.

### 4.2 Required vs Optional Fields

**REQUIRED (absence = hard failure, blocks code extraction)**:

| Field | Type | Why Required |
|---|---|---|
| `code` | str (non-empty) | The model's fix. Without it, there is nothing to evaluate. |
| `bug_diagnosis` | str | The model's reasoning. Without it, reasoning classification is impossible. Absence → reasoning_correct=None (per parse gate). |

**OPTIONAL (absence = schema_compliant=False, does NOT block execution)**:

| Field | Type | Why Optional |
|---|---|---|
| `plan_steps` | list[dict] | Metadata about the model's strategy. Not needed for execution. |
| `revision_history` | list[dict] | Metadata about the model's self-correction trace. Not needed for execution. |
| `revision_history[].verification` | list[dict] | Per-step verification records. Research signal only. |
| `revision_history[].invariants_checked` | list[dict] | Invariant analysis records. Research signal only. |
| `revision_history[].changes_made` | list[dict] or null | Change descriptions. Research signal only. |
| `revision_history[].changes_made[].target` | str | Sub-field of change descriptions. Research signal only. |
| `revision_history[].changed_functions` | list[str] | Function names modified. Research signal only. |
| `revision_history[].code_before` | str | Pre-revision code snapshot. Research signal only. |
| `revision_history[].code_after` | str | Post-revision code snapshot. Research signal only. |
| `verification` | list[dict] | Top-level verification summary. Research signal only. |
| `internal_revisions` | int | Revision count. Research signal only. |

**Handling of partial compliance**: Extra fields in the output are silently ignored (never cause failure). Missing optional fields are recorded in `schema_violations` but do not affect `parse_error`, `code_extracted`, or execution.

### 4.3 Retry Harness Parser: Same Principle

`parse_structured_output()` currently requires `reasoning`, `plan`, `code`. Under the new design:

- `code` is REQUIRED (hard failure if absent)
- `reasoning` is REQUIRED for classification (absence → reasoning_correct=None via parse gate)
- `plan` is OPTIONAL (absence → schema_compliant=False, does not block execution)

### 4.4 Reconstructor: Salvage-First for Code Extraction

`reconstruct_strict()` currently fails on missing files. Under the new design:

- If ANY model file contains code → extract it (code_extracted=True)
- If file path keys don't match manifest → schema_compliant=False
- Use `reconstruct_salvage()` as the PRIMARY code extraction path (fill missing with originals)
- Record path mismatches in `schema_violations`
- `reconstruct_strict()` becomes the schema compliance check, not the extraction gate

---

## 5. Metric Redefinition

### Three Independent Metrics

| Metric | Formula | What It Measures |
|---|---|---|
| `execution_pass_rate` | `sum(exec_pass) / N_total` | Fraction of cases where the model's code passes invariant tests. THE primary metric. Uses ALL cases regardless of schema compliance. |
| `schema_compliance_rate` | `sum(schema_compliant) / N_total` | Fraction of cases where the model's output conforms to the required metadata structure. Research signal about instruction-following quality. |
| `code_extraction_rate` | `sum(code_extracted) / N_total` | Fraction of cases where code was successfully extracted from the model output. Infrastructure health metric. |

### Derived Metrics

| Metric | Formula | What It Measures |
|---|---|---|
| `true_parse_failure_rate` | `sum(NOT code_extracted) / N_total` | Fraction where NO code could be found at all. These are genuine model failures (garbage output, broken JSON). |
| `execution_pass_given_extracted` | `sum(exec_pass) / sum(code_extracted)` | Pass rate AMONG cases where code was extracted. Comparable across models regardless of parse formatting. |
| `schema_penalty_rate` | `sum(exec_pass AND NOT schema_compliant) / N_total` | Cases where the model got the code RIGHT but formatted metadata wrong. This is the measurement artifact the fix eliminates. |

### Reporting Requirements

Every results table MUST include: `N_total`, `N_extracted`, `N_not_extracted`, `execution_pass_rate`, `schema_compliance_rate`, `code_extraction_rate`.

Cross-model comparison MUST use `execution_pass_rate` (not a rate that excludes schema-noncompliant cases).

---

## 6. Cross-Model Consistency Guarantee

### The Invariant

> For any two models M1 and M2: if M1 and M2 produce identical code for a case (byte-for-byte), they MUST receive identical execution_pass scores, regardless of how they format their metadata.

### How It Is Enforced

1. **Code extraction is format-agnostic**: The extraction layer tries multiple strategies (JSON field, code block, raw text) to find code. It does not care about metadata structure.

2. **Execution is code-only**: `exec_evaluate()` receives a code string. It has no visibility into whether that code came from a perfectly-structured LEG response or a malformed JSON with metadata errors.

3. **Schema compliance is reported separately**: It does not affect execution_pass. A model with 100% schema compliance and 50% execution pass rate is not "better" than a model with 0% schema compliance and 80% execution pass rate — the second model is objectively better at the task.

4. **No model-specific rejection**: The parser does not have model-specific branches. All models go through the same extraction logic. The only branching is by output FORMAT (file_dict, code_dict, json_direct, etc.), which is determined by the model's response, not its identity.

### What Changes for Each Model

- **Models that format metadata correctly**: No change. execution_pass and schema_compliant are both computed.
- **Models that format metadata wrong but produce correct code**: Previously penalized (parse_error set, results discounted). Now: execution_pass=True, schema_compliant=False. The code is evaluated on its merits.
- **Models that produce garbage output**: Previously and now: code_extracted=False, execution blocked. No change.

---

## 7. Backward Compatibility

### Re-Evaluation of Previous Runs

Previous run data contains `raw_model_output` in `run_responses.jsonl`. The raw output can be re-parsed with the new parser to produce:
- `code_extracted` (was code present?)
- `schema_compliant` (did metadata match?)
- `execution_pass` (re-run exec_evaluate on extracted code)

**Re-evaluation script requirements**:
1. Read `run_responses.jsonl` from a previous run
2. Re-parse each raw output with the new split parser
3. Re-run exec_evaluate on extracted code
4. Produce comparison table: old_pass vs new_pass, old_parse_error vs new_parse_error

### Expected Changes

| Category | Count (from analysis) | Old Behavior | New Behavior | Change |
|---|---|---|---|---|
| Valid JSON, correct code, metadata mismatch | 6 | pass=True, parse_error=set, valid=False | pass=True, parse_error=None, schema_compliant=False | parse_error removed, schema_compliant captures the signal |
| Valid JSON, wrong code, metadata mismatch | 3 | pass=False, parse_error=set, valid=False | pass=False, parse_error=None, schema_compliant=False | Same execution result, cleaner error attribution |
| Invalid JSON (broken structure) | 2 | parse_error=set, code="" | parse_error=set, code_extracted=False | No change — these are genuine parse failures |

**Zero execution results change.** The code that reaches `exec_evaluate` is identical — the fix only changes whether `parse_error` is set and how metadata is reported.

### Old vs New Comparison

| Field | Old System | New System |
|---|---|---|
| `parse_error` | Set for metadata violations AND code extraction failures | Set ONLY for code extraction failures |
| `valid` / `schema_compliant` | Conflated with parse_error | Independent field: schema_compliant |
| `code_extracted` | Not tracked separately | Explicit field |
| `execution_pass` | Computed correctly (code WAS passed to exec_evaluate) | Unchanged |
| `schema_violations` | Embedded in parse_error string | Separate structured list |

---

## 8. Validation Plan

### Test 1: Valid JSON + Wrong Metadata → Code MUST Still Execute

**Input**: A LEG-reduction response with valid JSON, correct code in the `code` field, but `changes_made[0]` missing the `target` sub-field.

**Expected**:
- `code_extracted` = True
- `parse_error` = None
- `schema_compliant` = False
- `schema_violations` contains "changes_made[0]: missing 'target'"
- `exec_evaluate()` runs and returns pass/fail based on code correctness
- If code is correct: `execution_pass` = True

**Failure if**: `parse_error` is set, OR code is not passed to exec_evaluate, OR execution is blocked.

### Test 2: Valid JSON + Correct Code → Must Pass

**Input**: A perfectly-formatted LEG-reduction response with correct code, correct metadata, all fields present.

**Expected**:
- `code_extracted` = True
- `parse_error` = None
- `schema_compliant` = True
- `schema_violations` = []
- `execution_pass` = True

**Failure if**: Any field is wrong.

### Test 3: Invalid JSON → Must Fail Cleanly

**Input**: A response that is not valid JSON (e.g., model closed brace prematurely, or emitted markdown instead of JSON).

**Expected**:
- `code_extracted` = False
- `parse_error` = "no_json_object_found" or "json_decode_error: ..."
- `schema_compliant` = False (not applicable, but False by default)
- Execution does NOT run

**Failure if**: `code_extracted` = True (phantom code from garbage), or execution runs on non-code.

### Test 4: Extra Fields → Must NOT Cause Failure

**Input**: A LEG-reduction response with all required fields PLUS extra fields not in the schema (e.g., `"confidence": 0.9`, `"model_notes": "..."`, `"extra_analysis": {}`).

**Expected**:
- `code_extracted` = True
- `parse_error` = None
- `schema_compliant` = True (extra fields are ignored, not violations)
- Execution runs normally

**Failure if**: Extra fields cause parse_error, or schema_compliant=False.

### Test 5: Missing `plan` in Retry Harness → Code Still Extracted

**Input**: A retry harness response with `{"reasoning": "...", "code": "..."}` but missing `plan` field.

**Expected**:
- `code_extracted` = True (code field is present)
- `parse_error` = None
- `schema_compliant` = False (plan is expected but missing)
- Code is passed to exec_evaluate

**Failure if**: Code is not extracted because plan is missing.

### Test 6: Reconstructor Path Mismatch → Code Still Extracted

**Input**: A file-dict response where the model uses `"config.py"` instead of `"code_snippets_v2/alias_config_a/config.py"` as the key.

**Expected**:
- Code is extracted from the value regardless of key mismatch
- `schema_compliant` = False (path does not match manifest)
- `code_extracted` = True
- Execution runs

**Failure if**: Code is lost because the path key didn't match.

### Test 7: Cross-Model Consistency

**Input**: Two responses with identical `code` content but different metadata formatting:
- Response A: perfect metadata schema
- Response B: metadata has 5 violations

**Expected**:
- Both produce identical `execution_pass` value
- A has `schema_compliant` = True, B has `schema_compliant` = False
- No other metric differences

**Failure if**: execution_pass differs between A and B.

---

## 9. Failure Mode Table

| Failure Type | Old Behavior | New Behavior |
|---|---|---|
| Valid JSON, correct code, missing metadata sub-field | parse_error set, valid=False, code still executes but flagged as parse failure | parse_error=None, schema_compliant=False, code executes cleanly, schema_violations records the issue |
| Valid JSON, correct code, count mismatch (internal_revisions vs revision_history) | parse_error set, valid=False | parse_error=None, schema_compliant=False, schema_violations records mismatch |
| Valid JSON, correct code, extra fields in output | Currently tolerated (extra fields ignored) | No change — extra fields still ignored |
| Valid JSON, missing `code` field entirely | parse_error set, code="" | parse_error set, code_extracted=False — unchanged, this is a real failure |
| Invalid JSON (broken braces) | parse_error set, code="" | parse_error set, code_extracted=False — unchanged |
| Empty model response | parse_error set | parse_error set — unchanged |
| Retry harness: missing `plan` field | parse_error="missing_key: plan", code lost | parse_error=None, schema_compliant=False, code extracted from JSON |
| Retry harness: `plan` is string instead of list | parse_error="plan_not_list", code lost | parse_error=None, schema_compliant=False, code extracted |
| Reconstructor: model used wrong file path keys | status=FAILED_MISSING_FILES, code not extracted | Salvage extraction used, code_extracted=True, schema_compliant=False |
| Reconstructor: model omitted one file entirely | status=FAILED_MISSING_FILES | Salvage fills missing with original, code_extracted=True, schema_compliant=False |
| Reconstructor: AST syntax error in model code | status=FAILED_SYNTAX_ERRORS | code_extracted=True, execution catches syntax error (as it should) |
| Any condition: model produces correct code in non-JSON format (e.g., markdown) | Falls through to code_block or raw_fallback parser tier | Same — code extracted via fallback tier. schema_compliant=False for non-JSON format. |

---

## 10. Implementation Order

1. **Split `parse_leg_reduction_output()`** into extraction phase + validation phase
2. **Modify `parse_structured_output()`** to extract code/reasoning even when plan is missing
3. **Modify reconstruction path** in `execution.py` to use salvage-first for code extraction
4. **Add `code_extracted`, `schema_compliant`, `schema_violations`** to all result dicts
5. **Remove `parse_error` from metadata-only failures** — only set for code extraction failures
6. **Update metrics computation** in `live_metrics.py` to use the three-signal model
7. **Write re-evaluation script** for previous runs
8. **Run validation tests** (Tests 1-7)
9. **Run re-evaluation** on one existing ablation to verify backward-compatible execution results

---

## 11. Impact Quantification (from the forensic analysis)

| Metric | Before Fix | After Fix | Change |
|---|---|---|---|
| Cases with parse_error set (LEG condition) | 11/58 (19%) | 2/58 (3%) — only genuine JSON failures | -16pp |
| Cases with correct code but flagged as parse failure | 6/58 (10%) | 0/58 (0%) | -10pp |
| execution_pass_rate (LEG condition) | Unchanged (code was already reaching exec_evaluate) | Unchanged | 0 |
| schema_compliance_rate (LEG condition, new metric) | N/A | ~81% (47/58 — the 11 failures minus 2 genuine) | New metric |
| Reasoning classification accuracy | Contaminated by parse_error on valid reasoning | Clean — parse_error only on genuine extraction failures | Improved |
