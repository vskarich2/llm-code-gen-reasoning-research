# Stabilization Patch Plan — Verified and Expanded

**Date:** 2026-03-26
**Status:** Implementation-ready. All claims verified against code and logs.

---

## 1. VERIFIED Root Cause Table

| RC | Name | Report Correct? | Location | Trigger | Impact | Severity |
|---|---|---|---|---|---|---|
| RC-1 | Markdown fences in file content | **VERIFIED** | reconstructor.py:89-92 | Model wraps code in ` ```python ``` ` inside JSON file value | AST validation fails → FAILED_SYNTAX_ERRORS → code lost | **CRITICAL** |
| RC-2 | Escaped newlines in file content | **VERIFIED** | reconstructor.py:89-92 | Model returns `\\n` instead of real newlines in file content | AST validation fails → code lost | **HIGH** |
| RC-3 | Malformed JSON (literal newlines) | **VERIFIED** | parse.py:171-194 | Nano emits literal newlines inside JSON strings | json.loads fails → all 7 tiers miss → raw_fallback → code+reasoning lost | **CRITICAL** |
| RC-4 | All-UNCHANGED assertion crash | **VERIFIED** | execution.py:237-243 | Model returns all files as UNCHANGED | AssertionError → run killed | **CRITICAL** |
| RC-5 | Recon failure loses code | **VERIFIED** | execution.py:225-226 | Any non-SUCCESS reconstruction status | parsed["code"] stays None → exec_evaluate gets None → "no extractable code" | **CRITICAL** |
| RC-6 | Sanity guard too coarse | **VERIFIED** | runner.py:_validate_execution_sanity | ran_rate < 50% when >= 10 evals | RuntimeError after all data is written. Metadata incomplete (no end_time). | **MEDIUM** |
| RC-7 | Rename errors | **PARTIALLY CORRECTED** | exec_eval.py:724-732 | Model doesn't define expected function | 12/33 (36%) are artifacts of RC-3/RC-5, not real model failures. 21/33 are genuine. | **LOW** (genuine ones) |

### Correction to Report: RC-7

The report stated rename errors are "truly model failures." This is WRONG for 36% of them. When parse/reconstruction fails and the raw JSON blob is treated as "code," `_assemble_program` finds no Python function definitions and flags a rename error. These are downstream symptoms of RC-3/RC-5, not independent model failures.

**After fixing RC-1 through RC-5, the artifact rename errors will disappear** because the code will be properly extracted.

---

## 2. Additional Issues Found (Beyond Report)

### AI-1: _build_parsed_response setdefault Does Not Override None

**Location:** execution.py:203
**Code:** `parse_result.setdefault("code", "")`
**Issue:** When `_try_file_dict` returns `"code": None`, `setdefault("code", "")` does NOT override it because the key already exists. `parsed["code"]` stays `None`.
**Impact:** After reconstruction failure, `parsed["code"]` is `None` (not `""`) when it reaches `exec_evaluate`. `exec_evaluate` handles both correctly (line 771: `if not code`), so this is not a behavioral bug, but it means the type of `parsed["code"]` is inconsistent — sometimes str, sometimes None.
**Severity:** LOW — no behavioral impact, but a type inconsistency.

### AI-2: run_repair_loop Does Not Pass file_paths

**Location:** execution.py:321
**Code:** `_attempt_and_evaluate(case, model, prompt)` (no file_paths)
**Issue:** `run_single` passes `file_paths` for V2 output instruction, but `run_repair_loop` does not. Models may still return file_dict format unprompted. If they do, reconstruction runs but the V2 output instruction was not appended, so the model was less likely to follow the format.
**Impact:** LOW — repair_loop is rarely affected because models mostly return code-key format when not instructed to use file-dict.
**Severity:** LOW.

### AI-3: Reconstruction Failure Does Not Record WHAT Failed in events.jsonl

**Location:** execution.py:282-283
**Code:** `ev["reconstruction_status"] = parsed.get("_reconstruction_status")` — but this is only in `run_single`, not propagated to events.jsonl.
**Issue:** events.jsonl does not contain `reconstruction_status` or `reconstruction_failure_type`. When 20 cases show pass=False for 4o-mini baseline, you cannot tell from events.jsonl whether it was a model failure or a reconstruction failure.
**Impact:** MEDIUM — debugging requires reading run.jsonl, not events.jsonl. Metrics aggregation from events.jsonl cannot distinguish failure causes.
**Severity:** MEDIUM.

### AI-4: FAILED_SYNTAX_ERRORS Reconstruction Still Populates files dict

**Location:** reconstructor.py:102-108
**Issue:** When reconstruction returns FAILED_SYNTAX_ERRORS, `recon.files` is populated with the (syntactically invalid) file content AND `recon.changed_files` is populated. But execution.py:225 only checks `recon.status != "SUCCESS"` and sets `_reconstruction_error = True` without using the files.
**Impact:** The code IS in `recon.files` and `recon.changed_files` but is never extracted. If the syntax error is due to fences/escaping (RC-1/RC-2), the code UNDER the formatting is valid.
**Severity:** Part of RC-5 — the recovery opportunity.

### AI-5: Duplicate Failure Counting in Metrics

**Issue:** When a case fails due to RC-3 (JSON parse failure → raw_fallback → code treated as JSON blob → rename error), it is counted as BOTH a parse failure AND a rename error. This double-counts the failure in any analysis that sums failure types.
**Impact:** Rename error counts are inflated by 36%. Any analysis summing parse failures + rename errors overcounts.
**Severity:** MEDIUM — affects metric interpretation.

---

## 3. Full Pipeline Wiring Map

```
model_output (raw string)
  │
  ▼
parse_model_response(raw)
  │ Guarantees: returns dict with code, reasoning, files, response_format, parse_error
  │ Hazards:
  │   - code can be None (file_dict format)
  │   - code can be "" (empty)
  │   - code can be the raw JSON blob (raw_fallback)
  │   - reasoning can be "" (lost in raw_fallback)
  │   - files can be None (non-file-dict format)
  │   - files values can contain markdown fences or escaped newlines
  │
  ▼
_build_parsed_response(parse_result, raw_output)
  │ Guarantees: adds raw_output, sets defaults for missing keys
  │ Hazards:
  │   - setdefault("code", "") does NOT override code=None
  │   - parsed["code"] can be None after this step
  │
  ▼
IF response_format in ("file_dict", "code_dict") AND files is truthy:
  │
  ▼
reconstruct_strict(manifest_paths, manifest_files, parsed["files"])
  │ Guarantees: returns ReconstructionResult with status
  │ Hazards:
  │   - AST validation rejects markdown-fenced code (RC-1)
  │   - AST validation rejects escaped-newline code (RC-2)
  │   - All-UNCHANGED returns SUCCESS with empty changed_files (RC-4)
  │   - FAILED_SYNTAX_ERRORS: files dict IS populated but not used (AI-4/RC-5)
  │   - FAILED_MISSING_FILES: files dict is empty
  │
  ├─ SUCCESS + changed_files non-empty:
  │    parsed["code"] = join(changed_parts)  ← CORRECT PATH
  │
  ├─ SUCCESS + changed_files empty (all UNCHANGED):
  │    parsed["code"] = ""  ← ASSERTION CRASH (RC-4)
  │
  └─ FAILED_*:
       parsed["_reconstruction_error"] = True
       parsed["code"] STAYS None  ← CODE LOST (RC-5)
  │
  ▼
evaluate_output(case, parsed)
  │ Assumes: parsed["code"] is a string (may be "" or short)
  │ Hazards:
  │   - parsed["code"] can be None → exec_evaluate handles it, but type is wrong
  │
  ▼
exec_evaluate(case, code)
  │ Guarantees: returns pass/fail/score
  │ Hazards:
  │   - code=None or code="" → "no extractable code" → pass=False
  │   - code=JSON blob (from raw_fallback) → syntax error or rename error
  │
  ▼
write_log / emit_event
  │ Hazards:
  │   - reconstruction_status not in events.jsonl (AI-3)
  │   - parse_category available in audit block but not in events
```

### Boundary Mismatches

| Boundary | Upstream Guarantees | Downstream Assumes | Mismatch |
|---|---|---|---|
| file_dict parser → reconstructor | File values are strings | File values are valid Python | **YES** — fences, escaped newlines |
| reconstructor (SUCCESS) → execution.py | changed_files may be empty | changed_files is non-empty | **YES** — all-UNCHANGED crashes |
| reconstructor (FAILED) → execution.py | recon.files may have recoverable content | Only SUCCESS path extracts code | **YES** — FAILED code is abandoned |
| parse_model_response → _build_parsed_response | code may be None (file_dict) | setdefault handles missing keys | **PARTIAL** — setdefault doesn't override None |
| _attempt_and_evaluate → evaluate_output | code is string or None | code is string | **YES** — None propagates |

---

## 4. Patch Plan (File-by-File, Function-by-Function)

### PATCH 1: Strip Markdown Fences in Reconstructor (RC-1)

**File:** `reconstructor.py`
**Function:** `reconstruct_strict`, between lines 87-92
**What:** Add a content normalization step before AST validation
**Anchor:** Between line 87 (`if not isinstance(value, str)...`) and line 89 (`ast.parse(value)`)

**Change:** Insert a function `_normalize_file_content(value)` that:
1. Strips leading ` ```python\n ` or ` ```\n ` prefix
2. Strips trailing ` \n``` ` or ` ``` ` suffix
3. Returns the cleaned string

Call it on `value` before `ast.parse`.

**Edge cases:**
- Content has ` ``` ` in the middle (not as fence) → only strip if it's at the very start/end
- Content has multiple ` ``` ` blocks → only strip outermost
- Content is just ` ``` ` with nothing inside → results in empty string → triggers FAILED_EMPTY_FILES (correct)

### PATCH 2: Unescape Newlines in Reconstructor (RC-2)

**File:** `reconstructor.py`
**Function:** `reconstruct_strict`, same location as PATCH 1
**What:** In `_normalize_file_content`, after fence stripping, if the content contains `\\n` but NO real newlines, replace `\\n` with `\n` and `\\t` with `\t`.

**Condition:** Only unescape when there are ZERO real newlines in the string. This distinguishes:
- `def f():\\n    pass` (escaped, needs unescape) — 0 real newlines
- `def f():\n    pass` (normal) — has real newlines, leave alone
- `def f():\\n    pass\n# comment` (mixed) — has real newlines, leave alone

### PATCH 3: Remove All-UNCHANGED Assertion (RC-4)

**File:** `execution.py`
**Function:** `_attempt_and_evaluate`, lines 237-243
**What:** Replace the assertion with correct handling of all-UNCHANGED:

```python
# Replace lines 237-243 with:
if not parsed["code"] or not parsed["code"].strip():
    # All files marked UNCHANGED — model believes original code is correct.
    # This is a valid (if usually wrong) model response.
    # Pass empty code to exec_evaluate — it will fail with
    # "no extractable code" which is the correct outcome.
    parsed["code"] = ""
```

**Edge cases:**
- Model marks all files UNCHANGED for a single-file case → single-file cases don't enter reconstruction (code_files_contents has 1 entry, skipped at exec_eval line 687). So this only affects multi-file cases. Correct.

### PATCH 4: Recover Code on Reconstruction Failure (RC-5)

**File:** `execution.py`
**Function:** `_attempt_and_evaluate`, lines 225-226
**What:** When reconstruction fails with FAILED_SYNTAX_ERRORS, attempt code recovery from the file content.

```python
# Replace lines 225-226 with:
if recon.status != "SUCCESS":
    parsed["_reconstruction_error"] = True
    # Attempt code recovery: reconstruct_strict may have populated
    # recon.files with content that has formatting issues.
    # Try to recover by normalizing content (strip fences, unescape).
    if recon.status == "FAILED_SYNTAX_ERRORS" and recon.files:
        from reconstructor import _normalize_file_content
        recovered_parts = []
        for p in manifest_paths:
            if p in recon.changed_files and p in recon.files:
                normalized = _normalize_file_content(recon.files[p])
                if normalized and normalized.strip():
                    recovered_parts.append(normalized)
        if recovered_parts:
            parsed["code"] = "\n\n".join(recovered_parts)
            parsed["_reconstruction_recovered"] = True
```

**Edge cases:**
- Normalization still fails AST → code is syntactically invalid Python → exec_evaluate catches SyntaxError (correct)
- No changed files in FAILED_SYNTAX_ERRORS → recovered_parts is empty → code stays None → "no extractable code" (correct)
- Mixed: some files normalize successfully, others don't → partial code → may produce assembly errors or partial fixes (acceptable — better than no code)

### PATCH 5: Lenient File-Dict Parser (RC-3, P1)

**File:** `parse.py`
**Function:** New `_try_file_dict_lenient(raw)`
**Where:** After `_try_file_dict` (tier 0), before `_try_code_dict` (tier 1a)
**What:** Handle JSON with literal newlines in file content strings.

Strategy: Extract `"files"` dict via regex (similar to `_try_json_lenient` for `"code"` key).

**This is P1, not P0.** The P0 fixes (PATCH 1-4) address reconstruction failures that affect ALL models. RC-3 specifically affects nano's malformed JSON. The lenient parser is more complex and can wait.

### PATCH 6: Sanity Guard Downgrade (RC-6, P1)

**File:** `runner.py`
**Function:** `_validate_execution_sanity`
**What:** Change all `raise RuntimeError(...)` to warnings. Always write end_time to metadata. Add `sanity_guard_triggered` flag to metadata.

**This is P1.** The guard fires AFTER data is written. Data is recoverable.

---

## 5. P0 / P1 / P2 Plan

### P0 — Must Fix Before Next Run

| # | Fix | Patch | Files | Changes Behavior? |
|---|---|---|---|---|
| P0-1 | Strip markdown fences from file content | PATCH 1 | reconstructor.py | YES — previously-failed cases now execute |
| P0-2 | Unescape \\n in file content | PATCH 2 | reconstructor.py | YES — same |
| P0-3 | Remove all-UNCHANGED assertion | PATCH 3 | execution.py | YES — no more crash on all-UNCHANGED |
| P0-4 | Recover code on recon failure | PATCH 4 | execution.py | YES — previously-lost code now executes |

### P1 — Should Fix Soon

| # | Fix | Patch | Files |
|---|---|---|---|
| P1-1 | Lenient file-dict parser | PATCH 5 | parse.py |
| P1-2 | Sanity guard downgrade | PATCH 6 | runner.py |
| P1-3 | Add reconstruction_status to events.jsonl | — | execution.py, live_metrics.py |
| P1-4 | Fix duplicate rename error counting | — | Analysis scripts (not runtime) |

### P2 — Cleanup

| # | Fix |
|---|---|
| P2-1 | Log all content normalizations (before/after) |
| P2-2 | Make parsed["code"] type consistently str, never None |
| P2-3 | Clean up crashed nano duplicate run directory |

---

## 6. Validation Tests

### Test P0-1: Markdown fences stripped

**Input:** File content = ` ```python\ndef create_config():\n    return dict(DEFAULTS)\n``` `
**Before fix:** `reconstruct_strict` returns FAILED_SYNTAX_ERRORS
**After fix:** Content normalized to `def create_config():\n    return dict(DEFAULTS)`. AST passes. Reconstruction SUCCESS. Code executes.

### Test P0-2: Escaped newlines unescaped

**Input:** File content = `def create_config():\\n    return dict(DEFAULTS)` (literal backslash-n, no real newlines)
**Before fix:** `ast.parse` fails with "unexpected character after line continuation character"
**After fix:** Content unescaped to `def create_config():\n    return dict(DEFAULTS)`. AST passes. Code executes.

### Test P0-3: All-UNCHANGED does not crash

**Input:** Model returns `{"files": {"a.py": "UNCHANGED", "b.py": "UNCHANGED"}}`
**Before fix:** AssertionError kills the run
**After fix:** Reconstruction SUCCESS. changed_files=empty. parsed["code"]="". exec_evaluate: "no extractable code". pass=False. No crash.

### Test P0-4: Code recovered from FAILED_SYNTAX_ERRORS

**Input:** Model returns file_dict where one file has markdown fences
**Before fix:** FAILED_SYNTAX_ERRORS → code=None → "no extractable code"
**After fix:** Recovery normalizes content → code extracted → code executes

### Test P0-COMBO: End-to-end on 4o-mini lost cases

**Input:** Re-run the 20 cases that had code_length=0 in the 4o-mini baseline
**Before fix:** 20/20 show "no extractable code"
**After fix:** Majority should now extract and execute code

### Test P0-REGRESSION: Existing passing cases unchanged

**Input:** 10 cases that currently pass for 4o-mini baseline
**Before fix:** All pass
**After fix:** All still pass (normalization should be no-op on valid content)

---

## 7. Impact Estimate After P0 Fixes

| Model | Baseline Cases Recovered | Previous Ran/58 | Expected Ran/58 |
|---|---|---|---|
| gpt-4.1-nano | ~9 (recon fixes) | 18 | ~27 |
| gpt-4o-mini | ~20 (all recon) | 34 | ~54 |
| gpt-5-mini | ~4 (recon fixes) | 53 | ~57 |
| gpt-5.4-mini | ~1 (crash fix) | 45/46* | 46/46** |

\* Out of 46 completed (run crashed at 92/116)
\** Full 58 cases, no crash

Note: nano still loses 29 baseline cases to RC-3 (malformed JSON). That requires P1-1 (lenient file-dict parser).

Summary of verification results and corrections:

  All 7 root causes from the original report were verified against code. One significant correction: RC-7 (rename errors) is 36%
  artifact, not 100% genuine model failures. 12 of 33 rename errors are downstream symptoms of parse/reconstruction failure — the
  JSON blob is treated as "code" and naturally has no Python function defs.

  5 additional issues found beyond the original report:
  - AI-1: setdefault("code", "") doesn't override None (type inconsistency)
  - AI-2: run_repair_loop doesn't pass file_paths (minor)
  - AI-3: reconstruction_status not in events.jsonl (observability gap)
  - AI-4: FAILED_SYNTAX_ERRORS has recoverable content in recon.files that is never used
  - AI-5: Duplicate failure counting (parse failure + rename error on same case)

  6 concrete patches specified with exact file, function, line range, what to change, edge cases, and whether behavior changes. 4
  are P0 (before next run), 2 are P1.

  6 validation tests defined with exact input, expected before-fix behavior, and expected after-fix behavior.

  Estimated impact: P0 fixes recover ~34 lost cases across models (20 for 4o-mini, 9 for nano, 4 for 5-mini, 1 for 5.4-mini).

