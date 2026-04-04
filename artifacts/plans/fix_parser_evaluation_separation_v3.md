# Plan: Separate Code Execution from Metadata Validation

**Version:** v3 (CONSOLIDATED FINAL)
**Date:** 2026-03-26
**Status:** Plan only. No code changes.
**Supersedes:** fix_parser_evaluation_separation_v2.md + addendum
**Scope:** leg_reduction.py, execution.py, parse.py, reconstructor.py, retry_harness.py

---

## CHANGELOG

| Version | Change | Rationale |
|---|---|---|
| v1→v2 | Added execution equivalence guarantee, removed salvage, added extraction invariant, tightened metrics, defined fallback policy | v1 had no proof of execution equivalence, unsafe salvage, no extraction verification |
| v2→v3 | LEG gets restricted fallback; retry harness gets best-of-two candidate selection; extraction source traceability added | v2 LEG "no fallback" discarded valid code; v2 retry "first wins" assumed strict extraction is always correct |

---

## 1. Root Cause Model

### Current Pipeline

```
model_output
  │
  ├─ Standard conditions: parse_model_response()
  │    7-tier fallback: file_dict → code_dict → JSON → lenient
  │    → substring → code_block → raw_fallback
  │    Result: {code, reasoning, parse_error, files}
  │
  ├─ LEG-reduction: parse_leg_reduction_output()
  │    1. Extract JSON → 2. Extract code field → 3. Validate metadata
  │    Result: {code, valid, parse_error, validation_errors}
  │
  ├─ Retry harness: parse_structured_output()
  │    Requires: reasoning, plan, code
  │    If fail → fallback to parse_model_response()
  │    Result: {code, reasoning, plan, valid_schema, parse_error}
  │
  ├─ V2 file-dict: reconstruct_strict()
  │    Requires: all manifest files present
  │    If missing → FAILED_MISSING_FILES
  │
  ▼
  parsed = {code, reasoning, parse_error, _raw_fallback}
  │
  ▼
  evaluate_output(case, parsed)
  ├─ exec_evaluate(case, parsed["code"])  ← code execution
  ├─ llm_classify(...)                     ← reasoning classification
  └─ result = {pass, score, reasoning_correct, ...}
```

### Where Valid Code Is Currently Dropped

**82% of failures** (9/11): Valid JSON containing correct code, rejected by `parse_leg_reduction_output()` metadata validator over incidental sub-fields (`changes_made[].target`, `internal_revisions` count, `verification` array length). These set `parse_error` even though code IS extracted and DOES pass execution.

**18% of failures** (2/11): Genuine JSON structural errors where the model lost track of brace nesting. Code exists in raw output but JSON extraction fails.

### Core Defect

`valid` and `parse_error` conflate two independent signals:
1. Did we extract usable code? (YES in 9/11 cases)
2. Did the metadata conform to the strict LEG schema? (NO in 9/11 cases)

---

## 2. Failure Type Separation

### Three Independent Signals

| Signal | Question | Source | Authority |
|---|---|---|---|
| **A. Execution Correctness** | Did the code pass invariant tests? | `exec_evaluate()` | SOLE authority for code correctness |
| **B. Schema Compliance** | Did output match required metadata structure? | Metadata validators | Research signal about instruction-following. NOT a gate on execution. |
| **C. Code Extraction** | Was code successfully extracted? | Parser output | Gate on execution: no code = no execution |

### After the Fix

Every case produces THREE independent fields:
```json
{
  "code_extracted": true,          // C
  "exec_pass": true,               // A
  "schema_compliant": false,       // B
  "schema_violations": ["..."],    // B details
  "parse_error": null              // Only set for C failures
}
```

`parse_error` is set ONLY when code extraction fails. Schema violations are recorded in `schema_violations` and NEVER set `parse_error`.

---

## 3. New Evaluation Contract

> Code execution MUST NOT depend on metadata schema compliance.

1. If the parser extracts non-empty code (>= 10 chars), `exec_evaluate()` runs.
2. Metadata validation errors record `schema_compliant=False` but do NOT block execution.
3. `parse_error` is set ONLY when no code is extractable.

### Required vs Optional Fields

**REQUIRED (absence = hard failure)**:

| Field | Type | Why |
|---|---|---|
| `code` | non-empty str | Without it, nothing to evaluate |
| `bug_diagnosis` | str | Without it, reasoning classification impossible (returns None) |

**OPTIONAL (absence = schema_compliant=False, execution proceeds)**:

All other LEG fields: `plan_steps`, `revision_history`, `verification`, `internal_revisions`, and all nested sub-fields (`changes_made[].target`, `invariants_checked`, etc.).

Extra fields in output are silently ignored (never cause failure).

---

## 4. Parser Redesign: Two-Phase Split

### Phase 1 — Code Extraction (always runs, never blocked by metadata)

1. Extract JSON from raw text
2. If JSON extraction fails → trigger restricted fallback (Section E.1)
3. Extract `code` field from parsed JSON
4. If `code` absent or empty → trigger restricted fallback (Section E.1)
5. Extract `bug_diagnosis` if present
6. Return: `{code, bug_diagnosis, code_extracted=True, parse_error=None}`

### Phase 2 — Metadata Validation (informational, never blocks execution)

1. Validate `plan_steps`, `revision_history`, all sub-fields
2. Validate consistency (counts, cross-references)
3. Return: `{schema_compliant, schema_violations, validity_score}`

Phase 1 failure blocks execution. Phase 2 failure is recorded but does NOT block execution and does NOT set `parse_error`.

---

## A. Execution Equivalence Guarantee

### A.1 Proof Obligation

The fix modifies what `parse_error` and `valid` are set to. It does NOT modify what code string reaches `exec_evaluate()`. This must be proven per code path.

### A.2 Path-by-Path Analysis

**Path 1 — LEG-reduction**: `lr_parsed["code"]` is set at line 300, BEFORE metadata validation (lines 327-477). The fix changes ONLY lines 495-528 (result construction). Code extraction logic is untouched. `parsed["code"]` reaching `exec_evaluate()` is byte-identical.

**Exception**: The new restricted fallback (Section E.1) fires when JSON extraction FAILS ENTIRELY. In the old system, these cases got `code=""` (hard failure). In the new system, fallback may recover code. This is a DELIBERATE DIVERGENCE — it recovers code that was previously lost. It affects only the 2/11 Category B cases. For the 9/11 Category A cases (JSON parses, metadata wrong), the code path is unchanged.

**Path 2 — Standard conditions**: `parse_model_response()` is NOT modified. Code reaching `exec_evaluate()` is byte-identical.

**Path 3 — Retry harness**: Both strict and fallback extractors now run (Section E.3). Best candidate is selected via C1-C3 criteria. This changes which code is executed in cases where the two extractors disagree. This is a DELIBERATE DIVERGENCE, verified via A.4.

### A.3 Divergence Classification

| Path | Divergence | Type | Verification |
|---|---|---|---|
| LEG (metadata errors) | NONE | N/A | Byte-identity test (Test 8) |
| LEG (JSON failure) | ALLOWED — code recovery | Deliberate improvement | Test 16 |
| Standard | NONE | N/A | Not modified |
| Retry harness | POSSIBLE — candidate selection | Must verify via A.4 | Test 9 |

### A.4 Verification Procedure (Mandatory Before Rollout)

1. **Capture baseline**: For each retry harness case, record the exact code string reaching `exec_evaluate()` under the CURRENT pipeline.
2. **Capture post-fix**: Same cases, NEW pipeline. Record code string.
3. **Byte-compare**: For every case, compare.
4. **Divergence policy**:
   - 0 divergences: equivalence proven.
   - > 0 divergences: for each, classify as "better extraction" (new code passes C1-C3, old did not) or "worse extraction" (new code fails where old succeeded).
   - ALL "better": allowed, documented.
   - ANY "worse": fix REJECTED for retry harness. Revert to old fallback.

### A.5 LEG Equivalence: Formal Statement

> For LEG cases where JSON extraction succeeds (Category A — 82%): `parsed_json["code"]` at line 300 is byte-identical before and after the fix. Lines 276-313 are not modified. `exec_evaluate()` receives byte-identical input.

> For LEG cases where JSON extraction fails (Category B — 18%): the old system produced `code=""`. The new system may recover code via fallback. This is a deliberate improvement, not an equivalence violation.

Enforced by Test 8 (byte-identity) and Test 16 (recovery).

---

## B. Reconstruction Rules (No Salvage)

### B.1 Why Salvage Is Unsafe

`reconstruct_salvage()` fills missing files with ORIGINAL BUGGY CODE, creating hybrid programs. This can produce false passes and unattributable results.

### B.2 Rules

1. `reconstruct_strict()` is the ONLY primary reconstruction path.
2. `reconstruct_salvage()` is FORBIDDEN for primary metrics. Assert failure if called.
3. Path normalization: if a model key's basename matches a manifest key's basename uniquely, remap the key. Lossless. Logged.
4. No hybrid programs: executed code is either 100% model code, or model + originals via `_assemble_program()` (existing behavior).

---

## C. Extraction Verification Invariant

### C.1 The Invariant

> `_assemble_program(parsed["code"], case)["code"]` == the string passed to `load_module_from_code()`.

### C.2 Enforcement

1. `exec_evaluate()` already records `_extracted_code` (pre-assembly input).
2. NEW: `exec_evaluate()` must also record `_assembled_code` (post-assembly, what was actually executed).
3. Test: `parsed["code"]` == `ev["_extracted_code"]` for all paths.
4. Test: `_assembled_code` is deterministic (same input → same output).

---

## D. Metric Definitions

### D.1 Primary Metrics

```
execution_pass_rate(C)     = count(exec_pass == True) / N_total
code_extraction_rate(C)    = count(code_extracted == True) / N_total
schema_compliance_rate(C)  = count(schema_compliant == True) / N_total
```

Denominator is ALWAYS `N_total`. No conditional exclusions.

### D.2 Derived Metrics

```
true_parse_failure_rate(C) = count(code_extracted == False) / N_total
schema_penalty_rate(C)     = count(exec_pass == True AND schema_compliant == False) / N_total
```

### D.3 Missing Value Policy

| Field | Missing? | Default |
|---|---|---|
| `exec_pass` | NEVER | N/A |
| `code_extracted` | NEVER | N/A |
| `schema_compliant` | NEVER | False if code not extracted |
| `schema_violations` | NEVER | [] if compliant |
| `parse_error` | Allowed (None) | None when no extraction failure |
| `extraction_source` | NEVER | Required for all cases |
| `extraction_conflict` | NEVER | False if no conflict |

### D.4 Mapping Old Runs

```
execution_pass_rate = same as old (exec_evaluate unchanged for Category A)

code_extracted:
  old parse_error is None → True
  old parse_error contains "validation_errors" → True (code was in JSON)
  old parse_error contains "raw_fallback" → True
  old parse_error contains "no_json" or "empty" → False

schema_compliant:
  old valid == True AND parse_error is None → True
  old valid == False → False
  old parse_error contains "validation_errors" → False
```

Mapping is DETERMINISTIC.

---

## E. Fallback Policy

### E.1 LEG-Reduction: Restricted Fallback

**Primary path**: JSON `code` field via `parse_leg_reduction_output()`. If JSON parses and `code` field exists as non-empty string → FINAL. No fallback.

**Restricted fallback ONLY IF**:
- `_extract_json()` returns None (JSON extraction fails entirely), OR
- JSON parses but `code` field absent, OR
- JSON parses but `code` field empty or not a string

**Fallback procedure**:
1. Run `parse_model_response(raw_output)`.
2. If non-empty code extracted: use it. Set `extraction_source="fallback"`, `schema_compliant=False`, `parse_error=None`.
3. If no code: hard failure. `code_extracted=False`, `parse_error` set.

**Fallback MUST NOT**: run when JSON extraction produced non-empty code; silently override valid JSON extraction; omit `extraction_source`.

### E.2 Standard Conditions: Existing Fallback (Unchanged)

7-tier `parse_model_response()`. Not modified. `response_format` logged.

| Priority | Tier | Code Source |
|---|---|---|
| 0 | file_dict | Per-file content |
| 1a | code_dict | Per-file from `code` dict |
| 1b | json_direct | `code` field string |
| 1c | json_lenient | Regex-extracted `code` |
| 2 | json_substring | Substring-parsed `code` |
| 3 | code_block | Last ```python block |
| 4 | raw_fallback | Entire raw text |

### E.3 Retry Harness: Best-of-Two Candidate Selection

**Both extractors ALWAYS run**:
```
strict_code  = parse_structured_output(raw)["code"]
fallback_code = parse_model_response(raw).get("code") or ""
```

**Candidate set**: Include each if non-empty. If both produce identical string, one candidate (no conflict).

**Selection via deterministic criteria** (applied only when two DIFFERENT non-empty candidates exist):

| Criterion | Check | Eliminates |
|---|---|---|
| **C1: Syntax validity** | `ast.parse(code)` succeeds | Not valid Python |
| **C2: Non-trivial** | len >= 50 AND contains `def ` or `class ` | Placeholders, stubs |
| **C3: Length** (tiebreaker) | `len(code)` | Between two valid non-trivial candidates, prefer longer |

**Selection algorithm**:
1. Single candidate → use it.
2. Filter to C1-valid. 0 remain → prefer strict. 1 → use it.
3. Filter to C2-nontrivial. 0 → prefer strict from C1 set. 1 → use it.
4. C3 tiebreaker → longer wins.

**Record**: `extraction_source` ("strict" or "fallback"), `extraction_conflict` (True if candidates differed), `extraction_candidates` (source→length map).

### E.4 Reconstruction: No Salvage

`reconstruct_strict()` with path normalization. No salvage in primary path.

### E.5 Fallback Prohibitions

| Prohibition | Rationale |
|---|---|
| LEG fallback MUST NOT run when JSON extraction produced non-empty code | Primary path precedence |
| LEG fallback MUST set `extraction_source="fallback"` | Traceability |
| Salvage reconstruction MUST NOT be used for primary metrics | Hybrid programs |
| Raw fallback MUST be flagged `_raw_fallback=True` | Downstream awareness |
| Retry harness: no silent replacement of strict extraction | Both run; selection is explicit via C1-C3 |
| Retry harness: `extraction_conflict=True` MUST be logged | Reviewability |

---

## F. Explicit Invariants

1. **Extraction-Execution Identity (LEG, Category A)**: `lr_parsed["code"]` == code received by `exec_evaluate()` (before assembly). Guaranteed because extraction logic (lines 276-313) is unmodified.

2. **Extraction-Execution Identity (all paths, post-assembly)**: `_assemble_program(parsed["code"], case)["code"]` == string passed to `load_module_from_code()`.

3. **No Hybrid Programs**: Executed program is either model-only or model+originals via `_assemble_program()`. `reconstruct_salvage()` never called in primary path.

4. **parse_error Semantics**: Set ONLY for code extraction failures. Metadata violations set `schema_compliant=False`, never `parse_error`.

5. **Metric Exhaustiveness**: `exec_pass`, `code_extracted`, `schema_compliant` ALL defined for every case. No exclusions.

6. **Best-Available Extraction**: Executed code is the best candidate from all extraction sources, selected via deterministic C1-C3. Selection metadata always logged.

7. **Deterministic Assembly**: `_assemble_program()` is pure. Same input → same output.

8. **Extraction Source Traceability**: Every case records `extraction_source` ("strict", "fallback", "file_dict", "direct"). Missing = invalid.

9. **Extraction Conflict Logging**: If two sources produce different non-empty code, `extraction_conflict=True` and `extraction_candidates` recorded. Missing when conflict=True = invalid.

---

## G. Hard Failure Conditions

| Condition | Behavior |
|---|---|
| Empty model response | `code_extracted=False`, `parse_error="empty_response"`, execution blocked |
| LEG: no JSON found AND fallback finds no code | `code_extracted=False`, `parse_error` set |
| JSON parsed but `code` absent | `code_extracted=False`, `parse_error="missing_required_field: code"` |
| `code` not a string | `code_extracted=False`, `parse_error="code_not_str"` |
| `code` is empty string | `code_extracted=False`, `parse_error="code_empty"` |
| SyntaxError in `load_module_from_code()` | `exec_pass=False`, MODEL error (not infrastructure) |
| `reconstruct_salvage()` called in primary path | Assert failure — SYSTEM BUG |

---

## H. Validation Tests

### From v1 (retained)

| Test | Input | Expected |
|---|---|---|
| 1 | Valid JSON + wrong metadata | Code executes. `schema_compliant=False`, `parse_error=None` |
| 2 | Valid JSON + correct code | `exec_pass=True`, `schema_compliant=True` |
| 3 | Invalid JSON | `code_extracted=False`, `parse_error` set |
| 4 | Extra fields | No failure. `schema_compliant=True` |
| 5 | Retry: missing `plan` | Code extracted. `schema_compliant=False` |
| 6 | Reconstructor path mismatch | Path normalized. Code extracted. |
| 7 | Cross-model consistency | Identical code → identical `exec_pass` regardless of metadata |

### From v2 (retained)

| Test | Input | Expected |
|---|---|---|
| 8 | 10 LEG outputs with metadata errors | Code byte-identical old vs new parser |
| 9 | 10 retry harness outputs | Byte-identical OR all divergences are "better extraction" |
| 10 | Any reconstruction case | `reconstruct_salvage()` not called (assert) |
| 11 | 5 multi-file cases | `_assemble_program()` deterministic (run twice, byte-identical) |
| 12 | 20 mixed cases | Metric identities hold (rates sum to 1.0, all cases counted) |

### From v3 addendum (new)

| Test | Input | Expected |
|---|---|---|
| 13 | Retry: strict and fallback find same code | `extraction_source="strict"`, `extraction_conflict=False` |
| 14 | Retry: strict has placeholder, fallback has real code | `extraction_source="fallback"`, `extraction_conflict=True` |
| 15 | Retry: strict has valid code, fallback is garbage | `extraction_source="strict"` |
| 16 | LEG: broken JSON, but ```python block has code | `extraction_source="fallback"`, `code_extracted=True`, `parse_error=None` |
| 17 | LEG: valid JSON with non-empty `code` | `extraction_source="strict"`. Fallback does NOT run. |
| 18 | Retry: strict and fallback produce different code | `extraction_conflict=True`, `extraction_candidates` has 2 entries |

---

## I. Failure Mode Table

| Failure Type | Old Behavior | New Behavior |
|---|---|---|
| Valid JSON, correct code, missing metadata sub-field | `parse_error` set, `valid=False`, code executes but flagged | `parse_error=None`, `schema_compliant=False`, code executes cleanly |
| Valid JSON, correct code, count mismatch | `parse_error` set, `valid=False` | `parse_error=None`, `schema_compliant=False` |
| Valid JSON, correct code, extra fields | Tolerated | Tolerated (unchanged) |
| Valid JSON, missing `code` field | `parse_error` set, `code=""` | `parse_error` set, `code_extracted=False` (unchanged) |
| Invalid JSON (broken braces) | `parse_error` set, `code=""` | Fallback runs. If code found: `code_extracted=True`, `extraction_source="fallback"`. If not: hard failure. |
| Empty response | `parse_error` set | Unchanged |
| Retry: missing `plan` | `parse_error`, code via fallback | Code from strict parser (if present) or fallback. Best selected via C1-C3. |
| Retry: `plan` is string not list | `parse_error`, code via fallback | Same as above |
| Retry: strict has placeholder, fallback has code | Strict placeholder used (BUG) | Fallback code selected via C2 |
| Reconstructor: wrong file path keys | FAILED_MISSING_FILES | Path normalization applied first. If resolved: SUCCESS. |
| Reconstructor: model omitted file entirely | FAILED_MISSING_FILES | Same (path normalization cannot help if file is absent) |
| Reconstructor: AST syntax error | FAILED_SYNTAX_ERRORS | `code_extracted=True`, execution catches syntax error |

---

## J. Implementation Order

1. Split `parse_leg_reduction_output()` into extraction + validation phases
2. Add restricted fallback for LEG (Section E.1)
3. Implement candidate selection for retry harness (Section E.3)
4. Add path normalization to reconstructor (Section B.2 Rule 3)
5. Add `code_extracted`, `schema_compliant`, `schema_violations`, `extraction_source`, `extraction_conflict` to all result dicts
6. Remove `parse_error` from metadata-only failures
7. Add `_assembled_code` to `exec_evaluate()` result
8. Run verification procedure A.4 (byte-compare retry harness)
9. Run all 18 validation tests
10. Update metrics computation in `live_metrics.py`
11. Write re-evaluation script for old runs

---

## K. Impact Quantification

| Metric | Before | After | Change |
|---|---|---|---|
| Cases with `parse_error` set (LEG) | 11/58 (19%) | 0/58 (0%) — genuine failures get `code_extracted=False` or `extraction_source="fallback"` | -19pp of mislabeled parse errors |
| Correct code flagged as parse failure | 6/58 (10%) | 0/58 (0%) | -10pp |
| Code recovered from broken JSON | 0/58 | ~2/58 (3%) — via restricted fallback | +2 cases evaluated |
| `execution_pass_rate` (LEG) | Unchanged for Category A cases | +possible gains from Category B recovery | 0 to +3pp |
| `schema_compliance_rate` (new metric) | N/A | ~81% | New signal |
