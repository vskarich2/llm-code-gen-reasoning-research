# Forensic Stability Audit: Single-Trial Ablation Run

**Date:** 2026-03-26
**Scope:** All rerun_* directories from the most recent single-trial ablation
**Models:** gpt-4.1-nano, gpt-4o-mini, gpt-5-mini, gpt-5.4-mini
**Conditions:** baseline, leg_reduction
**Cases:** 58 (cases_v2.json)

---

## 1. Executive Summary

**The current system has three critical defects that make baseline results unreliable for weaker models and cause partial run failures for all models.**

The most serious stability risks:

1. **Reconstruction rejects valid code due to cosmetic formatting** (markdown fences in file content, escaped newlines). This is the single largest source of data loss, affecting 20/58 baseline cases for gpt-4o-mini and 9/58 for nano. The code EXISTS in the model output but is discarded because the reconstructor performs AST validation on content that includes markdown fences. This is not a model failure — it is an infrastructure rejection of valid solutions.

2. **Malformed JSON from nano** (literal newlines in JSON strings) falls through ALL 7 parser tiers to raw_fallback, which loses both code and reasoning. 29/58 baseline cases for nano. The `_try_file_dict` tier has no lenient fallback, unlike `_try_json_lenient` for the code-key format.

3. **All-UNCHANGED response causes assertion crash** (gpt-5.4-mini, cache_invalidation_order). The assertion at execution.py:239 conflates "model returned no changes" with "wiring is broken." This killed the 5.4-mini run at 92/116, losing 12 cases.

**Trustworthiness assessment:**
- **gpt-5-mini**: Results are trustworthy. 0 parse failures, 4 reconstruction failures, 88.8% ran rate. Usable for analysis.
- **gpt-5.4-mini**: Results are trustworthy for the 92 cases that completed. Missing 12 cases due to crash. Usable with caveat.
- **gpt-4o-mini**: Baseline results are **contaminated**. 20/58 cases (34%) lost code due to reconstruction syntax-error rejection. The 34/58 that ran are valid, but the 20/58 that show code_length=0 are infrastructure failures, not model failures. LEG-reduction results are clean (0 reconstruction failures).
- **gpt-4.1-nano**: Baseline results are **severely contaminated**. 29/58 (50%) lost to JSON parse failure + 9/58 lost to reconstruction. Only 18/58 (31%) actually ran code. LEG-reduction results are usable (0 parse/recon failures, 36/58 ran).

**Top-priority P0 fixes before next run:**
1. Strip markdown fences from file-dict content before AST validation
2. Unescape `\\n` to `\n` in file-dict content after JSON parsing
3. Remove the all-UNCHANGED assertion crash
4. Add lenient file-dict parser for malformed JSON with literal newlines

---

## 2. Run Forensics: Last Single-Trial Ablation

### Model-by-Model Timeline

**gpt-4.1-nano (rerun_gpt-4.1-nano_t1_27f3a089)**
- 116/116 events written (both conditions complete)
- Crashed AFTER completion with `EXECUTION SANITY FAILED: ran_rate=44.8% < 50%`
- 29 baseline cases hit CODE_LOST (malformed JSON → raw_fallback → reasoning lost → parse gate)
- 9 baseline cases had code_length=0 from reconstruction failure
- 12 baseline rename errors
- 19 baseline syntax errors
- Net: only 18/58 baseline cases actually executed code
- LEG-reduction: 0 parse failures, 36/58 ran, 24 passed

**gpt-4o-mini (rerun_gpt-4o-mini_t1_2e33567b)**
- 116/116 events written
- Did NOT crash (ran_rate=69.8% > 50%)
- 2 baseline cases hit CODE_LOST (malformed JSON)
- 20 baseline cases had code_length=0 from reconstruction FAILED_SYNTAX_ERRORS
- Root cause for reconstruction failures: 14 markdown fences in file content, 5 escaped newlines, 1 other
- Net: only 34/58 baseline cases executed code
- LEG-reduction: 0 parse/recon failures, 47/58 ran, 34 passed

**gpt-5-mini (rerun_gpt-5-mini_t1_61a45d51)**
- 116/116 events written
- Did NOT crash
- 0 parse failures
- 4 baseline reconstruction failures (syntax errors — markdown fences)
- Net: 53/58 baseline cases executed code
- LEG-reduction: 0 parse/recon failures, 50/58 ran, 43 passed

**gpt-5.4-mini (rerun_gpt-5.4-mini_t1_aa6cee54)**
- 92/116 events (INCOMPLETE — crashed at case `cache_invalidation_order`)
- Crash: `AssertionError: INVARIANT VIOLATION: reconstruction status=SUCCESS but parsed['code'] is empty`
- Cause: model returned all 4 files as UNCHANGED. changed_files=empty set. Assertion at execution.py:239 fires.
- 12 cases lost (never evaluated)
- Before crash: 45/46 baseline ran, 43 passed. 41/46 LEG ran, 40 passed.

### Failure Classification

| Failure Type | nano BL | nano LR | 4o-mini BL | 4o-mini LR | 5-mini BL | 5-mini LR | 5.4-mini BL | 5.4-mini LR |
|---|---|---|---|---|---|---|---|---|
| Parse (CODE_LOST) | 29 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| Recon fail (fences) | 7 | 0 | 14 | 0 | 4 | 0 | 0 | 0 |
| Recon fail (escaped \\n) | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 |
| Recon fail (other) | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| Rename error | 12 | 6 | 4 | 7 | 1 | 2 | 1 | 0 |
| Syntax error | 19 | 16 | 0 | 4 | 0 | 6 | 0 | 5 |
| Assembly error | 0 | 5 | 0 | 5 | 0 | 4 | 0 | 0 |
| Crash (assertion) | 0 | 0 | 0 | 0 | 0 | 0 | 1* | 0 |

\* Killed the entire run at 92/116.

**Key observation:** Parse and reconstruction failures affect ONLY baseline, never LEG-reduction. This is because LEG uses `raw=True` (no file-dict output instruction) and extracts code directly from JSON `code` field, bypassing the reconstruction path entirely.

---

## 3. Root Cause Inventory

### RC-1: Markdown Fences in File-Dict Content

**Location:** `reconstructor.py:89-92` (AST validation step)
**Trigger:** Model wraps code in ` ```python ... ``` ` inside the JSON file content string.
**Symptoms:** `RECONSTRUCTION FAILED: syntax errors in N files`; code_length=0; case not executed.
**Root cause:** `reconstruct_strict()` calls `ast.parse(value)` on each file's content. If the content starts with ` ```python `, ast.parse rejects it as invalid Python. The code IS valid Python — it just has markdown fencing around it.
**Affected models:** gpt-4o-mini (14 cases), gpt-4.1-nano (7 cases), gpt-5-mini (4 cases), gpt-5.4-mini (0).
**Severity:** **CRITICAL** — 25 cases across models lose valid code. Baseline execution rates are artificially depressed.
**Threatens:** Scientific validity (baseline pass rates are wrong), software stability (no).

### RC-2: Escaped Newlines in File-Dict Content

**Location:** `reconstructor.py:89-92` (AST validation step)
**Trigger:** Model returns `\\n` (literal backslash-n) instead of actual newline characters in file content strings. JSON correctly parses these as `\n` characters, producing code like `def f():\\n    pass` instead of `def f():\n    pass`.
**Symptoms:** `RECONSTRUCTION FAILED: syntax errors`; code_length=0.
**Root cause:** Some models (gpt-4o-mini, 5 cases) double-escape newlines. After `json.loads()`, the string contains literal `\n` characters rather than actual newlines. ast.parse fails.
**Affected models:** gpt-4o-mini (5 cases).
**Severity:** **HIGH** — 5 cases lose valid code.
**Threatens:** Scientific validity.

### RC-3: Malformed JSON from Nano (Literal Newlines in Strings)

**Location:** `parse.py:171-194` (`_try_file_dict`)
**Trigger:** gpt-4.1-nano emits JSON with literal newline characters inside string values (not escaped). `json.loads()` rejects this as invalid JSON.
**Symptoms:** All 7 parser tiers fail. Raw_fallback fires. Entire response becomes "code." Reasoning lost. Parse gate fires CODE_LOST.
**Root cause:** `_try_file_dict()` relies on `json.loads()` which requires properly escaped strings. There is no lenient file-dict parser equivalent to `_try_json_lenient()` (which handles the code-key format with literal newlines).
**Affected models:** gpt-4.1-nano (29 baseline cases — 50%).
**Severity:** **CRITICAL** — 29 cases completely lost (no code, no reasoning).
**Threatens:** Scientific validity (nano baseline is useless), software stability (run crashes on sanity guard).

### RC-4: All-UNCHANGED Assertion Crash

**Location:** `execution.py:237-243`
**Trigger:** Model returns all files as `"UNCHANGED"`. Reconstruction succeeds (status=SUCCESS). changed_files is empty. Assertion fires because it assumes SUCCESS must produce non-empty changed_files.
**Symptoms:** `AssertionError: INVARIANT VIOLATION: reconstruction status=SUCCESS but parsed['code'] is empty.` Run killed immediately.
**Root cause:** The assertion conflates "no changes needed" with "wiring is broken." All-UNCHANGED is a LEGAL model response (model believes original code is correct). The assertion is wrong.
**Affected models:** gpt-5.4-mini (1 case: cache_invalidation_order). Could affect any model.
**Severity:** **CRITICAL** — Kills the entire run, losing all subsequent cases.
**Threatens:** Software stability (run crash), scientific validity (12 missing cases).

### RC-5: Reconstruction Failure Loses Code Silently

**Location:** `execution.py:225-226`
**Trigger:** `reconstruct_strict()` returns any non-SUCCESS status.
**Symptoms:** `parsed["_reconstruction_error"] = True`. `parsed["code"]` stays None (from file_dict parser). `exec_evaluate` gets code=None → "no extractable code."
**Root cause:** When reconstruction fails, there is NO fallback to extract code from the file content. The code IS in `parsed["files"]` but is never recovered. The comment at line 229 explains the SUCCESS path but there is no error-path code recovery.
**Affected:** Every case where RC-1 or RC-2 triggers.
**Severity:** **CRITICAL** — This is the amplifier that turns a cosmetic formatting issue into total code loss.
**Threatens:** Scientific validity.

### RC-6: Sanity Guard Too Coarse

**Location:** `runner.py:_validate_execution_sanity()` (lines 383-440)
**Trigger:** `ran_rate < 50%` with >= 10 total evals.
**Symptoms:** `RuntimeError: EXECUTION SANITY FAILED`. Run crashes after all evaluations complete.
**Root cause:** The guard does not distinguish between parse/recon infrastructure failures and genuine model failures. When 50% of cases fail due to RC-1/RC-3 (parser gaps), the guard fires as if the pipeline is broken. But the pipeline IS working — it just can't handle certain output formats.
**Affected:** gpt-4.1-nano (ran_rate=44.8% triggers crash).
**Severity:** **MEDIUM** — The data was already written to events.jsonl before the guard fires, so the data is recoverable. But the run is marked as failed and metadata is incomplete (no end_time).
**Threatens:** Run completeness, operational stability.

### RC-7: Rename Errors Across All Models

**Location:** `exec_eval.py:724-732` (`_assemble_program`)
**Trigger:** Model produces code that doesn't define the expected entry function.
**Symptoms:** `RENAME DETECTED: case X expects model to define 'Y' but model defines: [Z]`. Code not executed.
**Root cause:** This is a GENUINE MODEL FAILURE — the model renamed or omitted the target function. NOT an infrastructure issue.
**Affected:** All models. nano: 12+6, 4o-mini: 4+7, 5-mini: 1+2, 5.4-mini: 1+0.
**Severity:** **LOW** — Correct behavior. Model genuinely failed to produce the right function signature.
**Threatens:** Nothing — this is working as designed.

---

## 4. Parsing Audit

### Parser Tier Inventory

| Tier | Function | Format | Lenient Variant? | Coverage |
|---|---|---|---|---|
| 0 | `_try_file_dict` | `{"files": {...}}` | **NO** | Requires valid json.loads |
| 1a | `_try_code_dict` | `{"code": {file: content}}` | **NO** | Requires valid json.loads |
| 1b | `_try_json_direct` | `{"code": "str"}` | **NO** | Requires valid json.loads |
| 1c | `_try_json_lenient` | `{"code": "str"}` with literal newlines | **YES** | Handles unescaped newlines for "code" key |
| 2 | `_try_json_substring` | Embedded JSON in text | **NO** | Regex-based |
| 3 | `_try_code_block` | ` ```python ... ``` ` | N/A | Markdown extraction |
| 4 | raw_fallback | Entire text | N/A | Last resort |

### Asymmetry Matrix

| Format Issue | "code" Key Path | "files" Key Path | Gap? |
|---|---|---|---|
| Valid JSON | _try_json_direct | _try_file_dict | No |
| Literal newlines in strings | **_try_json_lenient (HANDLED)** | **NOTHING (UNHANDLED)** | **YES — RC-3** |
| Code wrapped in markdown fences | Not applicable (code is direct) | **UNHANDLED by reconstructor** | **YES — RC-1** |
| Escaped \\n in code content | Handled (code runs with \\n, may syntax-error) | **UNHANDLED by reconstructor** | **YES — RC-2** |

### Parser Gaps (Concrete)

1. **No lenient file-dict parser.** `_try_json_lenient` handles `{"reasoning": "...", "code": "..."}` with literal newlines. No equivalent handles `{"reasoning": "...", "files": {"path": "..."}}` with literal newlines. This is the exact gap that causes RC-3.

2. **Reconstructor performs AST validation before code execution.** Code that has markdown fences can have the fences stripped. Code that has escaped newlines can be unescaped. The reconstructor rejects both as "syntax errors" when they are formatting artifacts, not code defects.

3. **No post-parse content normalization.** After JSON parsing succeeds, file content strings are used as-is. No step strips ` ```python ` wrappers or unescapes `\\n` sequences. This normalization is trivially correct and would eliminate RC-1 and RC-2.

4. **Reconstruction failure has no code recovery.** When `reconstruct_strict` fails, `parsed["code"]` stays None. The file content IS available in `parsed["files"]` but is never extracted as a fallback. A simple concatenation of file values (after stripping fences) would recover the code.

---

## 5. Wiring / Data Plumbing Audit

### Stage-by-Stage Handoff Map

```
call_model(prompt)
  → raw_output (str)

parse_model_response(raw_output)
  → parsed = {code, reasoning, files, response_format, parse_error}

  IF response_format == "file_dict" AND files is not None:
    reconstruct_strict(manifest_paths, manifest_files, parsed["files"])
      → recon = {status, files, changed_files, syntax_errors}

      IF status == SUCCESS:
        parsed["code"] = join(changed_parts)        ← can be EMPTY if all UNCHANGED
        assert parsed["code"] is non-empty           ← CRASH on all-UNCHANGED (RC-4)
      ELSE:
        parsed["_reconstruction_error"] = True
        parsed["code"] STAYS None                    ← CODE LOST (RC-5)

evaluate_output(case, parsed)
  → exec_evaluate(case, parsed["code"])
    IF code is None or len < 10:
      → "no extractable code", pass=False
```

### Mismatch: Upstream Guarantee vs Downstream Assumption

| Stage | Upstream Guarantees | Downstream Assumes | Mismatch? |
|---|---|---|---|
| file_dict parser → reconstructor | Files dict has string values | File content is valid Python | **YES — content may have fences/escaped newlines** |
| reconstructor → execution.py | SUCCESS means all files present | SUCCESS means changed_files non-empty | **YES — all-UNCHANGED is legal but crashes** |
| reconstructor (failure) → execution.py | Code available in parsed["files"] | Code available in parsed["code"] | **YES — failure path loses code** |
| parse_model_response → evaluator | code may be None for file_dict | code is a non-empty string | **YES — file_dict sets code=None** |

### Empty/Default/None Hazards

1. `parsed["code"] = None` after file_dict parsing. If reconstruction fails, code stays None. Nobody sets it to anything else.
2. `parsed["code"] = ""` after all-UNCHANGED reconstruction. The assertion crashes before this can propagate.
3. `_build_parsed_response` sets `parse_result.setdefault("code", "")` but this is BEFORE the file_dict reconstruction branch overwrites code.

### Information Loss Points

1. **Reconstruction failure:** `parsed["files"]` contains the model's code but it is never read again after reconstruction fails.
2. **Raw fallback:** `parsed["reasoning"] = ""` when the entire response becomes "code." The reasoning IS in the raw text but is lost.
3. **Crashed run (5.4-mini):** 12 cases never evaluated, never logged to events.jsonl, responses not in run_responses.jsonl.

---

## 6. Reconstruction Edge-Case Audit

### All-UNCHANGED Behavior

**Is all-UNCHANGED a legal model response?** YES. It means the model believes the original code is correct and no changes are needed. This is a valid (if wrong) assessment.

**What should happen?** The execution should proceed with the original code. `pass` should be True if the original code is correct (unlikely — it has a known bug), False if it has the bug (expected). The result category should be `true_failure` (wrong reasoning + wrong code) or `lucky_fix` (wrong reasoning + code happens to pass).

**What currently happens?** Assertion crash. Run killed. 12 cases lost.

**The assertion at execution.py:239 is wrong.** It assumes:
> If reconstruction succeeds, the model must have changed something.

This is not a wiring invariant. It is a domain assumption that does not hold. The assertion should be REMOVED or replaced with a warning.

### What Invariant Should Be Enforced?

The correct invariant is:
> If reconstruction succeeds, `recon.files` must contain entries for all manifest paths.

This is already checked by `reconstruct_strict` (missing files → FAILED_MISSING_FILES). The empty-changed_files case is a logical outcome, not a bug.

### Adjacent Edge Cases

1. **Model marks some files UNCHANGED but changes others.** This is the normal case. changed_files is non-empty. Works correctly.
2. **Model adds extra files not in manifest.** `recon.extra_files` records them. They are ignored. Works correctly.
3. **Model returns empty string for a file.** `reconstruct_strict` returns FAILED_EMPTY_FILES. Code is lost (RC-5).
4. **Model returns the original code verbatim (not UNCHANGED).** `reconstruct_strict` marks it as changed. The code is correct but redundant. Works correctly.

---

## 7. Sanity Guard Audit

### Current Guards (in `_validate_execution_sanity`)

| Guard | Threshold | Triggers on | Behavior |
|---|---|---|---|
| ran_rate < 50% | 50% with >= 10 evals | Low execution rate | RuntimeError (crashes run) |
| pass_rate == 0 | 0% with >= 10 evals | Zero passes | RuntimeError |
| Zero variance | 1 category with >= 10 evals | All same category | RuntimeError |
| LEG rate > 95% | 95% with >= 20 evals | Extreme LEG | RuntimeError |

### Assessment

**ran_rate < 50%:** This guard is INCORRECTLY SPECIFIED for runs with parser/reconstruction gaps. When 29/58 baseline cases fail due to malformed JSON (RC-3), the ran_rate drops to 44.8%, triggering the guard — but this is NOT "pipeline broken." The pipeline is working; it just can't parse nano's output. The guard should distinguish infra failures from model failures.

**pass_rate == 0:** This guard is reasonable but could false-positive on weak models with high parse failure rates.

**Recommendation:** Guards should WARN and ANNOTATE, not CRASH. The data is already written to events.jsonl. Crashing after evaluation destroys metadata (no end_time) and makes the run appear invalid when the data IS valid.

---

## 8. Logging and Observability Gaps

### What Is Missing

1. **Reconstruction failure cause is not in events.jsonl.** events.jsonl has `pass`, `score`, `category` but not `reconstruction_status` or `reconstruction_failure_type`. When 20 4o-mini baseline cases show pass=False, you cannot tell from events.jsonl alone whether it was a model failure or a reconstruction failure.

2. **File-content normalization is not logged.** If we add fence-stripping or newline-unescaping, every case that triggers it must be logged with the original and normalized content.

3. **Sanity guard trigger is not in events.jsonl.** The guard fires AFTER events are written, so the events are fine — but there's no explicit marker in the run metadata that says "this run triggered sanity guard but data is valid."

4. **Reconstruction failure type is buried in runner_output.txt.** The only way to find out that a case had a reconstruction syntax error is to grep runner_output.txt. This information should be in the structured run.jsonl audit block.

### Minimal Instrumentation Plan

1. Add `reconstruction_status` and `reconstruction_failure_type` to events.jsonl schema.
2. Add `content_normalized` flag to audit block when fence-stripping or unescape runs.
3. Change sanity guard from RuntimeError to warning + metadata annotation.

---

## 9. Concrete Stabilization Plan

### P0 — Must Fix Before Next Run

| # | Problem | Fix | Files | Risk | Changes Behavior? |
|---|---|---|---|---|---|
| P0-1 | Markdown fences in file content cause recon failure (RC-1) | Strip ` ```python ` and ` ``` ` from file content strings BEFORE AST validation in reconstructor | `reconstructor.py:88-92` | LOW — purely cosmetic stripping | YES — cases that previously failed will now execute. Pass rates change. |
| P0-2 | Escaped newlines in file content cause recon failure (RC-2) | After JSON parsing, replace `\\n` with `\n` and `\\t` with `\t` in file content strings when the content has no real newlines | `reconstructor.py:62-78` or `execution.py:218-222` | LOW — standard unescape | YES — same as P0-1 |
| P0-3 | All-UNCHANGED assertion crash (RC-4) | Remove assertion at execution.py:239. Replace with: if changed_files is empty, set code="" and proceed (model chose "no changes") | `execution.py:237-243` | LOW — removes crash | YES — all-UNCHANGED cases will now evaluate (and fail, correctly) |
| P0-4 | Recon failure loses code silently (RC-5) | When reconstruction fails with FAILED_SYNTAX_ERRORS, attempt code recovery: concatenate file values after stripping fences/unescaping | `execution.py:225-226` | MEDIUM — new code path | YES — previously-lost code now executes |

### P1 — Should Fix Soon

| # | Problem | Fix | Files | Risk |
|---|---|---|---|---|
| P1-1 | No lenient file-dict parser (RC-3) | Add `_try_file_dict_lenient()` that handles literal newlines in JSON strings, analogous to `_try_json_lenient()` | `parse.py` | MEDIUM |
| P1-2 | Sanity guard too coarse (RC-6) | Change guards from RuntimeError to warnings. Annotate metadata with guard status. Always write end_time. | `runner.py:_validate_execution_sanity` | LOW |
| P1-3 | Reconstruction status not in events.jsonl | Add `reconstruction_status` and `code_extraction_method` to event schema | `execution.py`, `live_metrics.py` | LOW |

### P2 — Cleanup / Follow-Up

| # | Problem | Fix |
|---|---|---|
| P2-1 | Content normalization logging | Log every fence-strip and unescape operation with before/after |
| P2-2 | Runner_output.txt not always present | Ensure runner_output.txt exists for all runs including those launched without shell redirect |
| P2-3 | Duplicate nano run directory | Clean up `rerun_gpt-4.1-nano_t1_84764564` (crashed duplicate) |

---

## 10. Hard Recommendations Before Next Run

### Go/No-Go Criteria

The next ablation MUST NOT be launched until ALL of the following are true:

1. [ ] P0-1 implemented: markdown fences stripped from file content before AST validation
2. [ ] P0-2 implemented: escaped newlines unescaped in file content
3. [ ] P0-3 implemented: all-UNCHANGED assertion removed, replaced with correct handling
4. [ ] P0-4 implemented: reconstruction failure has code recovery path
5. [ ] P0 tests pass: new tests for each P0 fix verify the edge case is handled
6. [ ] Canary run (3 cases) passes for all 4 models without crash
7. [ ] Rerun 5 cases from the "20 lost 4o-mini cases" and verify they now produce code

### What Can Wait

- P1-1 (lenient file-dict parser): Only affects nano. Nano baseline will still have ~29 CODE_LOST cases without this fix. Acceptable for now — nano is the weakest model and this is a known, quantified gap.
- P1-2 (sanity guard): The guard only fires AFTER data is written. Data is recoverable. Annoying but not data-losing.
- P1-3 (event schema): Observability improvement, not correctness fix.

### Validation Tests Required

For each P0 fix, the following test must pass:

- **P0-1 test:** File content with ` ```python\ndef f(): pass\n``` ` → AST validation passes after stripping → code executes
- **P0-2 test:** File content with `def f():\\n    pass` (escaped newlines) → unescaped → AST passes → code executes
- **P0-3 test:** All files UNCHANGED → reconstruction SUCCESS → code="" → exec_evaluate runs with original (assembled) code → no crash
- **P0-4 test:** Reconstruction FAILED_SYNTAX_ERRORS but file content has valid code under fences → code recovered → code executes
