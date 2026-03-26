# Plan: Separate Code Execution from Metadata Validation

**Version:** v2
**Date:** 2026-03-26
**Status:** Plan only. No code changes.
**Supersedes:** fix_parser_evaluation_separation.md (v1)
**Scope:** leg_reduction.py, execution.py, parse.py, reconstructor.py

---

## CHANGELOG (v1 -> v2)

| Change | Section | Rationale |
|---|---|---|
| Added execution equivalence guarantee | A | v1 claimed "zero execution results change" without proof. v2 defines exact verification procedure. |
| Removed salvage-first reconstruction | B | Salvage mixes model + original code, producing hybrid programs. Replaced with strict path-normalization. |
| Added extraction verification invariant | C | v1 did not verify extracted code == executed code. v2 defines the invariant and enforcement. |
| Tightened metric definitions | D | v1 lacked exact denominators and missing-value handling. v2 defines formulas precisely. |
| Defined explicit fallback policy | E | v1 introduced fallback extraction without bounds. v2 defines exact tiers, priority, and prohibitions. |

All v1 content not explicitly revised below is carried forward unchanged (root cause model, pipeline diagram, failure mode table, validation tests, implementation order).

---

## A. Execution Equivalence Guarantee

### A.1 The Claim and Its Proof Obligation

The fix modifies what `parse_error` and `valid` fields are set to. It does NOT modify what code string reaches `exec_evaluate()`. This must be proven for each of the three code paths.

### A.2 Path-by-Path Analysis

**Path 1: LEG-reduction (`run_leg_reduction` in execution.py:461-526)**

Current code flow:
```
raw_output = call_model(prompt, model=model, raw=True)
lr_parsed = parse_leg_reduction_output(raw_output)
parsed = {"code": lr_parsed["code"], ...}
ev = evaluate_output(case, parsed)
  → exec_evaluate(case, parsed["code"])
```

`lr_parsed["code"]` is set at `leg_reduction.py:505`: `"code": code` where `code = parsed["code"]` at line 300. This extraction happens at line 300, BEFORE the metadata validation loop (lines 327-477). The validation loop records errors but never modifies `code`.

**The fix changes**: What `lr_parsed["parse_error"]` and `lr_parsed["valid"]` are set to. It does NOT touch lines 276-313 (JSON extraction and top-level field extraction). The `code` variable assigned at line 300 is unchanged.

**Therefore**: `parsed["code"]` reaching `exec_evaluate()` is byte-identical before and after the fix.

**Path 2: Standard conditions (`_attempt_and_evaluate` in execution.py:207-250)**

Current code flow:
```
parsed = parse_model_response(raw_output)
  → 7-tier fallback, extracts parsed["code"]
ev = evaluate_output(case, parsed)
  → exec_evaluate(case, parsed["code"])
```

**The fix does NOT modify `parse_model_response()`**. That function is not in scope. The fix only changes how downstream code interprets `parse_error` and `valid` from the LEG parser. Standard conditions never call `parse_leg_reduction_output()`.

**Therefore**: Code reaching `exec_evaluate()` is byte-identical.

**Path 3: Retry harness (`run_retry_harness` in retry_harness.py:1057-1082)**

Current code flow:
```
parsed = parse_structured_output(raw)
if not valid_schema:
    legacy = parse_model_response(raw)
    code_k = legacy.get("code") or ""
eval_parsed = {"code": code_k, ...}
ev = _safe_evaluate(case, eval_parsed)
```

**For the retry harness**: The fix changes `parse_structured_output()` to extract code even when `plan` is missing — but ONLY if the strict parser currently fails (valid_schema=False). In the current system, when valid_schema=False, code falls through to `parse_model_response()` at line 1066. In the new system, code would be extracted directly by the strict parser.

**THIS IS A POTENTIAL DIVERGENCE.** If `parse_structured_output()` now extracts code from JSON where it previously failed, and `parse_model_response()` would have extracted the SAME code via a different tier, the result is the same. But if `parse_model_response()` would have extracted DIFFERENT code (e.g., from a code block instead of the JSON field), the executed code changes.

### A.3 Divergence Classification

| Path | Change to Executed Code | Allowed? |
|---|---|---|
| LEG-reduction | NONE. Code extraction at line 300 is before validation. Fix only changes metadata fields. | N/A — no divergence |
| Standard conditions | NONE. `parse_model_response()` is not modified. | N/A — no divergence |
| Retry harness (missing `plan`) | POSSIBLE. Strict parser may now return code that was previously extracted via fallback. | Must be verified — see A.4 |
| Reconstruction (file-dict) | POSSIBLE if reconstruction path changes. | Must be verified — see Section B |

### A.4 Verification Procedure

**Before implementing the retry harness parser change**, the following procedure MUST be executed:

1. **Capture baseline**: Run existing ablation data through the CURRENT pipeline. For each case in retry conditions, record:
   - `code_before`: the exact code string that reaches `exec_evaluate()`
   - `pass_before`: the execution result

2. **Capture post-fix**: Run the same raw outputs through the NEW pipeline. Record:
   - `code_after`: the exact code string that reaches `exec_evaluate()`
   - `pass_after`: the execution result

3. **Equivalence check**: For every case:
   - If `code_before == code_after` (byte equality): PASS. No divergence.
   - If `code_before != code_after`: DIVERGENCE. Log the case, both code strings, and both execution results.

4. **Divergence policy**:
   - If divergence count is 0: equivalence proven.
   - If divergence count > 0: for each divergent case, determine:
     - Is the NEW code a better extraction? (i.e., did the old fallback lose code that the new direct extraction preserves?)
     - Is the NEW code a worse extraction? (i.e., did the old fallback find code that the new parser misses?)
   - If ALL divergences are "better extraction" (new code is a strict superset of old code's correctness): divergence is ALLOWED and documented.
   - If ANY divergence is "worse extraction": the fix is REJECTED for that path. Revert to the old fallback behavior for retry harness.

5. **Implementation**: The verification script captures `code_before` by running `exec_evaluate()` in logging mode (already available via `_extracted_code` in the result dict). `code_after` is captured the same way with the new parser.

### A.5 LEG-Reduction Equivalence: Formal Statement

For the LEG-reduction path specifically, the guarantee is stronger:

> The code string passed to `exec_evaluate()` is derived from `parsed_json["code"]` (line 300 of leg_reduction.py). The fix modifies ONLY lines 495-528 (result construction). Lines 276-313 (JSON extraction and field access) are NOT modified. Therefore `parsed_json["code"]` is byte-identical before and after the fix, and `exec_evaluate()` receives byte-identical input.

This guarantee holds because the fix is a METADATA-ONLY change: it changes what `valid`, `parse_error`, and `validation_errors` are set to, without touching the code extraction logic.

**This must be enforced as a test**: After implementation, a test MUST assert that for 10 LEG cases with metadata validation errors, the `code` field extracted by the old parser and the new parser are byte-identical.

---

## B. Reconstruction Rules (Revised — No Salvage)

### B.1 Why Salvage-First Is Unsafe

The v1 plan proposed using `reconstruct_salvage()` as the primary code extraction path. This is REJECTED because salvage MIXES model code with original buggy code:

```python
# reconstruct_salvage fills missing files with ORIGINALS
for rel_path in manifest_file_paths:
    if rel_path not in model_files:
        final_files[rel_path] = manifest_files[rel_path]  # ORIGINAL BUGGY CODE
```

This creates hybrid programs where some files are the model's fix and others are the original bugs. Such a program can:
- **False pass**: If the test only checks the file the model changed, the unchanged buggy files don't affect the result. But the "fix" is incomplete — the model only fixed one file.
- **False fail**: If the original buggy file interacts with the model's fix in unexpected ways.
- **Unattributable results**: The pass/fail is a property of the HYBRID, not of the model's output alone.

### B.2 Revised Reconstruction Rules

**Rule 1 — Strict reconstruction is the ONLY path for primary metrics.** `reconstruct_strict()` continues to be used. If it fails (FAILED_MISSING_FILES), the case is logged as a reconstruction failure, not a code failure.

**Rule 2 — Salvage is FORBIDDEN for primary metrics.** `reconstruct_salvage()` is used ONLY for secondary analysis (e.g., "what would have happened if we filled in the missing files?"). Results from salvage MUST be tagged and NEVER blended with primary results.

**Rule 3 — Path normalization for missing-key cases.** The specific failure where a model uses `"config.py"` instead of `"code_snippets_v2/alias_config_a/config.py"` is handled by KEY NORMALIZATION, not salvage:

- Before calling `reconstruct_strict()`, normalize model file keys: if a model key's basename matches a manifest key's basename AND no other manifest key has the same basename, map the model key to the manifest key.
- This is a LOSSLESS operation — no code is modified, only the dictionary key is renamed.
- Log every normalization: `"path_normalized: 'config.py' → 'code_snippets_v2/alias_config_a/config.py'"`
- If normalization resolves all missing files, reconstruction proceeds with `reconstruct_strict()`.
- If normalization does NOT resolve all missing files, reconstruction fails as before.

**Rule 4 — No hybrid programs.** The executed program is EITHER:
- 100% model code (single-file cases, or reconstruction SUCCESS), OR
- Model code assembled with originals via `_assemble_program()` (which is the EXISTING behavior for multi-file cases — originals as base, model code overlaid)

`_assemble_program()` is the ONLY place where model and original code mix, and it exists today. The fix does NOT introduce any new mixing path.

### B.3 What This Means for the Forensic Findings

The 9 cases with metadata mismatches: their code already reaches `exec_evaluate()` via the LEG-reduction path (not reconstruction). Reconstruction is only relevant for standard conditions using the V2 file-dict format. The LEG path extracts code directly from the JSON `code` field — no reconstruction involved.

---

## C. Extraction Verification Invariant

### C.1 The Invariant

> The code string extracted by the parser MUST be byte-identical to the code string received by `exec_evaluate()`, modulo the assembly step (which is documented, deterministic, and identical before and after the fix).

Formally:

```
extracted_code = parser_output["code"]
assembled_code = _assemble_program(extracted_code, case)["code"]
executed_code = the string passed to load_module_from_code()

INVARIANT: assembled_code == executed_code
```

### C.2 Current Enforcement

This invariant is ALREADY partially enforced:
- `exec_evaluate()` at line 769 captures `extracted = code` (the input code string)
- `exec_evaluate()` at line 778 calls `_assemble_program(code, case)` and gets `assembled_code`
- `exec_evaluate()` at line 808 calls `load_module_from_code(assembled_code, case_id)`
- The result dict at line 70 includes `_extracted_code` (the pre-assembly input)

### C.3 New Enforcement (Required by Fix)

After the fix, the following MUST be added:

1. **Store extracted_code in parsed dict**: The parser output must include the verbatim extracted code string, separate from any assembly.

2. **Store assembled_code in eval result**: `exec_evaluate()` must record `_assembled_code` (the post-assembly string that was actually executed) in its result dict.

3. **Verification test**: A test must assert that for 10 cases:
   - `parsed["code"]` == `ev["_extracted_code"]` (parser output matches exec input)
   - `ev["_assembled_code"]` is deterministic (running twice on the same input produces the same assembly)

### C.4 How Extracted Code Is Stored

For each code path:

| Path | Extracted Code Location | Assembly? | Executed Code |
|---|---|---|---|
| LEG-reduction | `lr_parsed["code"]` → `parsed["code"]` | Yes (multi-file) or No (single-file) | `_assemble_program(parsed["code"], case)["code"]` |
| Standard | `parse_model_response()["code"]` → `parsed["code"]` | Yes or No | `_assemble_program(parsed["code"], case)["code"]` |
| Retry harness | `parse_structured_output()["code"]` or fallback | Yes or No | `_assemble_program(code_k, case)["code"]` |
| V2 file-dict | `reconstruct_strict()` → joined changed_parts → `parsed["code"]` | Yes | `_assemble_program(parsed["code"], case)["code"]` |

In ALL paths, `exec_evaluate()` receives `parsed["code"]` and runs it through `_assemble_program()`. The fix does not change this flow.

---

## D. Metric Definitions (Revised — Exact Formulas)

### D.1 Primary Metrics

For each condition C, given N_total cases:

**Execution pass rate**:
```
execution_pass_rate(C) = count(cases where exec_pass == True) / N_total

Denominator: N_total (ALL cases, including code extraction failures).
Missing values: exec_pass is NEVER missing. If code was not extracted,
                exec_pass = False (code did not pass tests because it did not run).
```

**Code extraction rate**:
```
code_extraction_rate(C) = count(cases where code_extracted == True) / N_total

Denominator: N_total.
Missing values: code_extracted is NEVER missing. It is True if the parser
                produced a non-empty code string, False otherwise.
```

**Schema compliance rate**:
```
schema_compliance_rate(C) = count(cases where schema_compliant == True) / N_total

Denominator: N_total.
Missing values: schema_compliant is NEVER missing. It is True if ALL metadata
                validation checks passed, False if any failed, False if code
                was not extracted (cannot validate schema of missing output).
```

### D.2 Derived Metrics

**True parse failure rate**:
```
true_parse_failure_rate(C) = count(cases where code_extracted == False) / N_total

This is (1 - code_extraction_rate). It measures genuine extraction failures
(broken JSON, empty response), NOT metadata formatting issues.
```

**Schema penalty rate** (the measurement artifact):
```
schema_penalty_rate(C) = count(cases where exec_pass == True AND schema_compliant == False) / N_total

Cases where the model got the code RIGHT but formatted metadata wrong.
This is the artifact the fix eliminates from being conflated with parse_error.
```

### D.3 Missing Value Policy

| Field | Can It Be Missing? | Default | Justification |
|---|---|---|---|
| `exec_pass` | NO | N/A | exec_evaluate always returns pass (True/False) |
| `code_extracted` | NO | N/A | Determined by parser output; always known |
| `schema_compliant` | NO | False if code not extracted | If we can't parse the output at all, schema is non-compliant by definition |
| `schema_violations` | NO | [] if schema_compliant, else list | Always a list; empty means no violations |
| `parse_error` | YES (None when no error) | None | Only set for code extraction failures |

**No double counting**: Every case is counted exactly once in each metric's numerator or not. The denominators are always N_total. There are no conditional exclusions.

### D.4 Mapping Old Runs to New Metrics

Old runs have: `pass`, `parse_error`, `valid` (LEG only).

Mapping:
```
execution_pass_rate = same as old pass rate (exec_evaluate result unchanged)

code_extracted:
  - old parse_error is None → code_extracted = True
  - old parse_error contains "raw_fallback" → code_extracted = True (raw text used as code)
  - old parse_error contains "validation_errors" → code_extracted = True (code was in the JSON)
  - old parse_error contains "no_json_object_found" or "empty" → code_extracted = False

schema_compliant:
  - old valid == True AND old parse_error is None → schema_compliant = True
  - old valid == False (any reason) → schema_compliant = False
  - old parse_error contains "validation_errors" → schema_compliant = False
  - old parse_error is None AND response_format is "json_direct" → schema_compliant = True

schema_violations:
  - old validation_errors list → schema_violations (direct copy)
  - old parse_error string → parse to extract violation descriptions
```

This mapping is DETERMINISTIC — every old result maps to exactly one new result. The re-evaluation script applies this mapping to `run.jsonl` records.

---

## E. Fallback Policy (Explicit — No Hidden Paths)

### E.1 LEG-Reduction: NO Fallback

The LEG-reduction parser extracts code from the JSON `code` field. If code is present: success. If code is absent: hard failure. There is NO fallback to `parse_model_response()` or any other parser.

**Fallback tiers**: NONE. Single extraction path.

**Rationale**: LEG-reduction uses `raw=True` in the LLM call, which means no JSON output instruction is appended. The model is instructed to return a specific JSON schema. If the JSON doesn't contain `code`, there is no reasonable fallback — the model did not follow the instruction.

### E.2 Standard Conditions: Existing Fallback (Unchanged)

`parse_model_response()` has 7 tiers. These are NOT modified by this fix. The priority order:

| Priority | Tier | Condition | Code Source |
|---|---|---|---|
| 0 | file_dict | JSON has `files` key | Per-file content joined |
| 1a | code_dict | JSON has `code` as dict | Per-file content joined |
| 1b | json_direct | JSON has `code` as string | `code` field value |
| 1c | json_lenient | JSON malformed but code extractable via regex | Regex-extracted `code` value |
| 2 | json_substring | JSON embedded in text | Substring-parsed `code` value |
| 3 | code_block | ```python blocks | Last code block content |
| 4 | raw_fallback | None of the above | Entire raw text |

**Fallback is ALLOWED** for standard conditions because the LLM output instruction requests JSON but models frequently deviate.

**Fallback is ALWAYS logged**: `response_format` field records which tier succeeded.

### E.3 Retry Harness: Existing Fallback (Unchanged in Scope)

The retry harness tries `parse_structured_output()` first, then falls back to `parse_model_response()` if `valid_schema=False`.

**The fix changes** what `parse_structured_output()` considers a schema failure. Currently: missing `plan` → `valid_schema=False` → fallback to `parse_model_response()`. After the fix: missing `plan` → `valid_schema=False` BUT code and reasoning are still extracted from the strict parser → these are used directly → fallback still fires for code/reasoning extraction if strict parser found nothing.

**Critical constraint**: If the strict parser found code (code field present in JSON), that code is used. The fallback to `parse_model_response()` fires ONLY if the strict parser did not find code. This prevents the fallback from overriding a valid extraction with a different one.

**Implementation rule**:
```
parsed = parse_structured_output(raw)
code_k = parsed["code"]  # may be non-empty even if valid_schema=False

if not code_k.strip():
    # Strict parser found no code → fallback
    legacy = parse_model_response(raw)
    code_k = legacy.get("code") or ""
```

This is a REFINEMENT of the current logic (which falls back whenever `not valid_schema`, even if code was extracted). The refinement ONLY affects cases where the strict parser found code but reported schema failure due to missing `plan`. The verification procedure in A.4 catches any divergence.

### E.4 Reconstruction: No Salvage in Primary Path

Reconstruction uses `reconstruct_strict()` with path normalization (Section B.3). NO fallback to `reconstruct_salvage()` in primary metrics.

### E.5 Fallback Prohibitions

| Prohibition | Rationale |
|---|---|
| LEG parser MUST NOT fall back to `parse_model_response()` | LEG uses raw=True, so the output format is different. parse_model_response expects JSON with `code` key or code blocks, but LEG JSON has `code` inside a complex schema. The general parser would extract wrong content. |
| Salvage reconstruction MUST NOT be used for primary metrics | Produces hybrid programs mixing model and original code. |
| Raw fallback (tier 4) MUST be flagged with `_raw_fallback=True` | Downstream systems must know the code is the entire raw response, not extracted from structured output. |
| No fallback tier may OVERRIDE a successful higher-priority extraction | If tier 1b finds code, tier 3 does not run. If strict parser finds code, `parse_model_response()` does not override it. |

---

## F. Explicit Invariants (List Form)

1. **Extraction-Execution Identity (LEG path)**: `lr_parsed["code"]` == the code string received by `exec_evaluate()` (before assembly). This is guaranteed because the fix does not modify the extraction logic (lines 276-313 of leg_reduction.py).

2. **Extraction-Execution Identity (all paths, post-assembly)**: `_assemble_program(parsed["code"], case)["code"]` == the string passed to `load_module_from_code()`. This is guaranteed by the structure of `exec_evaluate()`.

3. **No Hybrid Programs (primary metrics)**: The executed program is either (a) model code only, or (b) model code assembled with originals via `_assemble_program()`. No other mixing path exists. `reconstruct_salvage()` is not called in the primary path.

4. **parse_error Semantics**: `parse_error` is set ONLY when code extraction fails (no code found in model output). Metadata validation failures set `schema_compliant=False` and populate `schema_violations`, but do NOT set `parse_error`.

5. **Metric Exhaustiveness**: For every case, `exec_pass`, `code_extracted`, and `schema_compliant` are ALL defined. No case is excluded from any metric denominator.

6. **Fallback Non-Override**: If a higher-priority parser tier successfully extracts code, no lower-priority tier may replace that extraction.

7. **Deterministic Assembly**: `_assemble_program(code, case)` is a pure function. Given identical inputs, it produces identical output. The fix does not modify `_assemble_program()`.

---

## G. Hard Failure Conditions (When the System MUST Fail)

| Condition | Failure Type | Behavior |
|---|---|---|
| Model response is empty or whitespace-only | Code extraction failure | `code_extracted=False`, `parse_error="empty_response"`, execution blocked |
| No JSON object found in LEG response | Code extraction failure | `code_extracted=False`, `parse_error="no_json_object_found"`, execution blocked |
| JSON parsed but `code` field absent | Code extraction failure | `code_extracted=False`, `parse_error="missing_required_field: code"`, execution blocked |
| JSON parsed, `code` field is not a string | Code extraction failure | `code_extracted=False`, `parse_error="code_not_str"`, execution blocked |
| JSON parsed, `code` field is empty string | Code extraction failure | `code_extracted=False`, `parse_error="code_empty"`, execution blocked |
| `_assemble_program()` called with empty code | Handled by exec_evaluate | Returns pass=False, "no extractable code" |
| `load_module_from_code()` raises SyntaxError | Execution error (not parse error) | `exec_pass=False`, syntax error logged. This is a MODEL error, not infrastructure. |
| Reconstruction finds missing files after path normalization | Schema failure (not code failure) | `schema_compliant=False`, `code_extracted` depends on whether any code was in the response |
| Salvage called in primary metric path | SYSTEM BUG | Assert failure — this must never happen |

---

## H. Validation Tests (Revised)

All 7 tests from v1 are retained. The following are ADDED:

### Test 8: Execution Equivalence (LEG path)

**Input**: 10 existing LEG-reduction raw outputs that have metadata validation errors but valid code.

**Procedure**:
1. Parse with OLD parser → extract code → record string
2. Parse with NEW parser → extract code → record string
3. Byte-compare

**Expected**: All 10 are byte-identical.
**Failure if**: Any pair differs.

### Test 9: Execution Equivalence (retry harness)

**Input**: 10 existing retry harness raw outputs.

**Procedure**: Same as Test 8 but for retry harness path.

**Expected**: All 10 are byte-identical OR divergences are "better extraction" per A.4 policy.
**Failure if**: Any divergence is "worse extraction."

### Test 10: No Salvage in Primary Path

**Input**: Any reconstruction-path case.

**Procedure**: Instrument `reconstruct_salvage()` to raise an error if called during primary evaluation.

**Expected**: No error raised during any primary evaluation.
**Failure if**: `reconstruct_salvage()` is called.

### Test 11: Assembly Determinism

**Input**: 5 multi-file cases.

**Procedure**: Run `_assemble_program(code, case)` twice on identical inputs.

**Expected**: Byte-identical output both times.
**Failure if**: Any difference.

### Test 12: Metric Completeness

**Input**: 20 cases with mixed results (some pass, some fail, some no extraction).

**Procedure**: Compute all metrics. Verify:
- `execution_pass_rate + execution_fail_rate == 1.0`
- `code_extraction_rate + true_parse_failure_rate == 1.0`
- Every case appears in exactly one category

**Expected**: All identities hold.
**Failure if**: Any identity violated or any case uncounted.
