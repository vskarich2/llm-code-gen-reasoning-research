# System-Wide Failure Exposure and Observability Plan

**Date:** 2026-03-26
**Status:** PLAN ONLY — No implementation.
**Scope:** All parsing, reconstruction, execution, evaluation, metrics, and logging paths.

---

## 1. GLOBAL FAILURE MODEL

### 1.1 Failure Classes

| Class | Subtype | Trigger | Current Behavior | Desired Behavior |
|---|---|---|---|---|
| **PARSE_FAILURE** | json_invalid | `json.loads()` fails | Falls through tiers; may hit raw_fallback | Classify explicitly. Log tier reached. Never silently become code. |
| **PARSE_FAILURE** | json_malformed_files | Files-format JSON with literal newlines | Falls through ALL tiers to raw_fallback. Code AND reasoning lost. | Lenient file-dict tier catches it. Content normalized. |
| **PARSE_FAILURE** | json_malformed_code | Code-format JSON with literal newlines | `_try_json_lenient` catches it | Already handled. Log as repaired. |
| **PARSE_FAILURE** | empty_response | Model returned nothing | Logged as SEVERE. Returns code="", reasoning="" | Correct. Classify as PARSE_FAILURE. |
| **PARSE_FAILURE** | raw_fallback | No tier matched | Entire response becomes "code". Reasoning="" | Must be explicitly classified. Must NOT count as executed code. |
| **RECONSTRUCTION_FAILURE** | missing_files | Model omitted expected files | FAILED_MISSING_FILES. Code=None. | Correct. Log explicitly. |
| **RECONSTRUCTION_FAILURE** | syntax_errors | AST validation fails on file content | FAILED_SYNTAX_ERRORS. Code lost (RC-5). | NOW FIXED: normalization + recovery. Log normalization. |
| **RECONSTRUCTION_FAILURE** | empty_files | Model returned empty file content | FAILED_EMPTY_FILES. Code=None. | Correct. Log explicitly. |
| **RECONSTRUCTION_FAILURE** | all_unchanged | Model marked all files UNCHANGED | WAS: assertion crash. NOW FIXED: returns SUCCESS, code="" | Correct. Log as model chose no changes. |
| **EXECUTION_FAILURE** | syntax_error | Model code has Python syntax error | SyntaxError caught. pass=False. | Correct. Classify as MODEL_FAILURE (code quality). |
| **EXECUTION_FAILURE** | runtime_error | Model code crashes at runtime | Exception caught. pass=False. | Correct. Classify as MODEL_FAILURE. |
| **EXECUTION_FAILURE** | no_code | code="" or code too short | "no extractable code". pass=False. | Correct, but upstream cause must be traced. |
| **EXECUTION_FAILURE** | rename_error | Model didn't define expected function | pass=False. ran=False. | SPLIT: genuine rename vs artifact of parse failure. Log upstream cause. |
| **EXECUTION_FAILURE** | assembly_error | Multi-file assembly fails (unresolved dep) | assembly_error=True. | Correct. Classify as SYSTEM_FAILURE if parse-related, MODEL_FAILURE if code-related. |
| **EVALUATION_FAILURE** | classifier_exception | LLM classifier call fails | reasoning_correct=None. | Correct. Classify as SYSTEM_FAILURE. |
| **EVALUATION_FAILURE** | classifier_parse_error | Classifier output malformed | reasoning_correct=None. | Correct. Log raw classifier output. |
| **EVALUATION_FAILURE** | reasoning_gated | Parse gate blocks classification | reasoning_correct=None. GATED. | Correct. Classify as PARSE_FAILURE (upstream). |
| **METRIC_FAILURE** | event_emission_failure | events.jsonl write fails | Warning logged. Event silently lost. (execution.py:189-190) | Must NOT silently lose events. Log failure AND mark run degraded. |
| **METRIC_FAILURE** | denominator_corruption | Unclassified cases change rate denominators | Currently computed correctly. | Report N_unclassified. Flag >10pp gap. |

### 1.2 Silent Failure Inventory (Current Code)

| File:Line | Current Behavior | Problem | Required Change |
|---|---|---|---|
| `parse.py:77` | `except (json.JSONDecodeError, TypeError): pass` in `_try_json_direct` | Silent fallthrough to next tier | Acceptable — multi-tier design. But the FINAL tier (raw_fallback) must be explicit. |
| `parse.py:120` | `except Exception: pass` in `_try_json_lenient` | Swallows ALL exceptions | Narrow to specific exceptions. Log unexpected ones. |
| `parse.py:251` | `except Exception: pass` in `_try_file_dict_lenient` | Same | Same |
| `parse.py:354-360` | raw_fallback: `code=raw.strip(), reasoning=""` | Entire response becomes "code". Reasoning silently lost. | Raw_fallback output MUST be flagged. Downstream must KNOW this is not real code. |
| `execution.py:186-190` | `except Exception as e: _exec_log.warning(...)` in `_emit_metrics_event` legacy path | Event silently lost | Log as degraded. Count lost events. |
| `execution.py:203-211` | `setdefault("code", "")` + None→"" normalization | Type coercion from None to "" | NOW FIXED (AI-1). Explicit normalization logged. |
| `evaluator.py:258-264` | `except Exception as e: ...` in `llm_classify` | Classifier failure returns None for all fields | Acceptable — but must propagate exception info to audit log. |
| `exec_eval.py:828` | `except Exception as e:` in `exec_evaluate` module loading | Generic catch-all | Narrows via `is_unresolved` heuristic. Acceptable but should classify more precisely. |

---

## 2. STAGE-BY-STAGE CONTRACT DESIGN

### Stage 1: Model Output → Parser

**Input contract:**
- `raw_output`: str (may be empty, malformed, or valid JSON)

**Output contract:**
```
{
    "code": str,                 # MUST be str, never None. "" if not extracted.
    "reasoning": str,            # MUST be str, never None. "" if not extracted.
    "files": dict | None,        # None for non-file-dict formats.
    "confidence": float | None,
    "parse_error": str | None,   # None if parsing succeeded cleanly.
    "response_format": str,      # MUST be set. Identifies which tier matched.
    "_raw_fallback": bool,       # True ONLY for tier 4 (raw_fallback).
}
```

**Required new fields:**
```
    "parse_tier": int,           # Which tier number matched (0-4).
    "parse_repaired": bool,      # True if any normalization/leniency was applied.
    "parse_repair_type": str | None,  # "lenient_json", "lenient_file_dict", None.
```

**Invalid states (must not occur):**
- `code` is None
- `response_format` is missing
- `_raw_fallback` is True AND `parse_error` is None (raw_fallback MUST have parse_error)

**On contract violation:** Raise `ValueError` with explicit message. This is a bug, not a model issue.

### Stage 2: Parser → Reconstruction

**Input contract:**
- `parsed["response_format"]` in `("file_dict", "code_dict", "file_dict_lenient")`
- `parsed["files"]` is a non-empty dict with str keys and str values

**Output contract:**
```
ReconstructionResult:
    status: str,                 # SUCCESS, FAILED_MISSING_FILES, FAILED_EMPTY_FILES, FAILED_SYNTAX_ERRORS
    files: dict[str, str],       # Populated on SUCCESS and FAILED_SYNTAX_ERRORS.
    changed_files: set[str],     # May be empty (all-UNCHANGED is legal).
    missing_files: set[str],
    extra_files: set[str],
    syntax_errors: dict[str, str],
```

**Required new fields:**
```
    content_normalized: bool,    # True if any file content was normalized (fences/escaping).
    normalization_log: list[str],  # Per-file normalization actions taken.
```

**Invalid states:**
- `status == "SUCCESS"` AND `files` is empty (would mean SUCCESS but nothing to show)
- `status == "FAILED_MISSING_FILES"` AND `missing_files` is empty (contradiction)

**On contract violation:** Raise `RuntimeError`. This is a bug.

### Stage 3: Reconstruction → Execution Handoff

**Input contract:**
- `parsed["code"]` is str (may be "")
- `parsed["_reconstruction_status"]` is set if reconstruction ran
- `parsed["_reconstruction_recovered"]` is bool

**Output contract to exec_evaluate:**
- `code`: str (may be "" — exec_evaluate handles this)

**Required new field in parsed:**
```
    "code_source": str,          # "json_code_field", "reconstruction", "reconstruction_recovery",
                                 # "fallback_parser", "raw_fallback", "leg_json"
```

**Invalid states:**
- `code` is None (AI-1 fix prevents this)
- `_reconstruction_status` is set but `_reconstruction_error` is missing

### Stage 4: Execution → Evaluation

**Input contract from exec_evaluate:**
```
{
    "pass": bool,
    "score": float,
    "reasons": list[str],
    "failure_modes": list[str],
    "execution": dict,           # Contains ran, syntax_error, runtime_error, etc.
    "_extracted_code": str,
    "_assembled_code": str,
}
```

**Required new field:**
```
    "failure_source": str,       # PRIMARY failure attribution (see taxonomy).
```

### Stage 5: Evaluation → Metrics/Logging

**Input contract from evaluate_output:**
All fields from exec_evaluate PLUS:
```
    "code_correct": bool,
    "reasoning_correct": bool | None,
    "failure_type": str | None,
    "alignment": dict,
    "eval_model_actual": str,
    "parse_category": str,
```

**Output to events.jsonl (REQUIRED fields — missing = invalid event):**
```
{
    "case_id": str,
    "model": str,
    "condition": str,
    "trial": int,
    "run_id": str,
    "timestamp": str,
    "pass": bool,
    "score": float,
    "reasoning_correct": bool | None,
    "code_correct": bool,
    "failure_type": str | None,
    "category": str,
    "num_attempts": int,
    "elapsed_seconds": float,
    # NEW required fields:
    "parse_tier": int,
    "parse_repaired": bool,
    "code_source": str,
    "reconstruction_status": str | None,
    "reconstruction_recovered": bool,
    "failure_source": str,
}
```

---

## 3. FAILURE TAXONOMY (STRICT)

### 3.1 Primary Failure Sources (Mutually Exclusive)

Every case gets EXACTLY ONE `failure_source`. Upstream failures take precedence.

```
PARSE_FAILURE
  → JSON could not be parsed. Code not extracted.
  → Subtypes: json_invalid, json_malformed, empty_response, raw_fallback_used

RECONSTRUCTION_FAILURE
  → JSON parsed but reconstruction failed. Code lost or recovered.
  → Subtypes: missing_files, empty_files, syntax_errors_unrecoverable

EXECUTION_FAILURE
  → Code extracted but could not execute.
  → Subtypes: syntax_error, runtime_error, no_code, assembly_error

MODEL_FAILURE
  → Code executed but failed tests.
  → Subtypes: invariant_fail, mutation_fail, rename_error (genuine only)

EVALUATION_FAILURE
  → Execution succeeded but classifier failed.
  → Subtypes: classifier_exception, classifier_parse_error, reasoning_gated

SUCCESS
  → Code extracted, executed, and passed. Reasoning classified.
```

### 3.2 Attribution Rules (Strict Precedence)

```
1. If parse_tier == raw_fallback AND code is JSON blob → PARSE_FAILURE
2. If reconstruction ran AND failed AND code not recovered → RECONSTRUCTION_FAILURE
3. If code == "" or len < 10 → EXECUTION_FAILURE:no_code (trace to upstream cause)
4. If syntax_error → EXECUTION_FAILURE:syntax_error
5. If rename_error AND parse_category in (CODE_LOST, raw_fallback) → PARSE_FAILURE (artifact)
6. If rename_error AND parse_category == CLEAN → MODEL_FAILURE:rename_error (genuine)
7. If ran AND not pass → MODEL_FAILURE
8. If reasoning_correct is None → tag EVALUATION_FAILURE alongside primary
9. If pass → SUCCESS
```

### 3.3 No Double Counting Rule

A case MUST have exactly ONE `failure_source`. If a case has both a parse failure AND a rename error, the failure_source is `PARSE_FAILURE` (upstream takes precedence). The rename error is a SYMPTOM, not an independent failure.

---

## 4. ERROR PROPAGATION DESIGN

### 4.1 Propagation Rules

| Failure Type | Raises Exception? | Execution Continues? | Logged Where? |
|---|---|---|---|
| JSON parse failure (any tier except last) | No — falls through to next tier | Yes | Final tier logs which tiers were tried |
| JSON raw_fallback | No | Yes — but code is likely garbage | SEVERE warning + parse_error set + _raw_fallback=True |
| Reconstruction FAILED_* | No | Yes — recovery attempted | Warning + _reconstruction_error=True |
| Reconstruction all-UNCHANGED | No | Yes — code="" | Info log |
| exec_evaluate syntax error | No (caught) | No (pass=False) | syntax_error field set |
| exec_evaluate runtime error | No (caught) | No (pass=False) | runtime_error field set |
| Classifier exception | No (caught) | Yes — reasoning_correct=None | classify_parse_error set |
| Event emission failure | No (caught) | Yes — event lost | WARNING logged (currently silent loss) |
| Assertion violation | YES — kills run | NO | Stack trace in runner_output.txt |

### 4.2 STOP Conditions (Hard Failures)

| Condition | Behavior | Rationale |
|---|---|---|
| Contract violation (None where str required) | Raise ValueError | Bug in pipeline code |
| No test function for case | Raise RuntimeError | Missing test = invalid benchmark |
| Log write after close | Raise RuntimeError | Run isolation bug |
| Model mismatch in logger | Raise RuntimeError | Cross-run contamination |

### 4.3 CONTINUE Conditions (Recoverable)

| Condition | Behavior | Tagging |
|---|---|---|
| Parse failure (any tier) | Fall through to next tier | parse_tier increments |
| Reconstruction failure | Recovery attempted | _reconstruction_recovered |
| Content normalization | Normalized content used | content_normalized=True |
| Classifier failure | reasoning_correct=None | classify_parse_error set |
| Low ran_rate | Warning (no crash) | sanity_warnings in metadata |

### 4.4 RECOVERY Conditions

| Recovery | When Allowed | When Forbidden | Logging |
|---|---|---|---|
| Lenient JSON parsing | json.loads fails on file-dict format | Never forbidden — it's a parser tier | parse_repair_type="lenient_file_dict" |
| Content normalization (fences) | File content starts with ``` | Normalization already applied | content_normalized=True per file |
| Content normalization (escapes) | File content has \\n but no real newlines | Content has real newlines (mixed) | content_normalized=True per file |
| Reconstruction recovery | FAILED_SYNTAX_ERRORS + recon.files has content | FAILED_MISSING_FILES (no content to recover) | _reconstruction_recovered=True |
| Raw fallback | All other tiers fail | Never — it's the last resort | _raw_fallback=True, parse_error set |

---

## 5. RECOVERY POLICY DESIGN

### 5.1 Universal Recovery Rules

1. **Every recovery is tagged.** The output must contain a field indicating recovery occurred.
2. **Every recovery is logged.** At minimum: what was recovered, from what state, to what state.
3. **No recovery is invisible.** A recovered result must be distinguishable from a native clean result.
4. **Recovery does not suppress failure classification.** A recovered parse is still tagged `parse_repaired=True`.

### 5.2 Recovery Tags

| Recovery Type | Field | Value |
|---|---|---|
| Lenient JSON parsing | `parse_repaired` | True |
| | `parse_repair_type` | "lenient_json" or "lenient_file_dict" |
| Content normalization | `content_normalized` | True (in ReconstructionResult) |
| Reconstruction recovery | `_reconstruction_recovered` | True |
| Raw fallback | `_raw_fallback` | True |

### 5.3 Forbidden Recoveries

| Situation | What Must NOT Happen |
|---|---|
| Raw_fallback produces JSON blob as "code" | This blob must NOT be executed as if it were Python. It should be tagged `code_source="raw_fallback"` and downstream should know it's not real code. |
| Reconstruction salvage in primary metrics | Salvage mixes model and original code. Forbidden for primary results. |
| Silent None→"" coercion without logging | The AI-1 fix must log when this normalization fires on a non-trivial case. |

---

## 6. PARSER SYMMETRY PLAN

### 6.1 Current Asymmetry

| Capability | "code" Key Format | "files" Key Format |
|---|---|---|
| Strict JSON parsing | `_try_json_direct` | `_try_file_dict` |
| Lenient JSON (literal newlines) | `_try_json_lenient` | `_try_file_dict_lenient` (NOW ADDED) |
| Content normalization (fences) | N/A (code is direct string) | `_normalize_file_content` (NOW ADDED) |
| Content normalization (escapes) | N/A | `_normalize_file_content` (NOW ADDED) |
| Substring extraction | `_try_json_substring` | No equivalent |
| Code block extraction | `_try_code_block` | No equivalent (files format not in code blocks) |

### 6.2 Symmetry Requirements

For every parser capability that exists for one format, there must be an equivalent for the other format, OR an explicit documented reason why it does not apply.

**JSON substring for files format**: NOT NEEDED. Files-format JSON is always the full response (not embedded in text). The only case where files JSON is malformed is literal newlines (handled by lenient tier).

**Code block for files format**: NOT NEEDED. Models that return files format never put it in code blocks.

### 6.3 Future Format Extension Rule

If a new output format is added:
1. It must have both strict and lenient parser tiers
2. It must have content normalization if applicable
3. It must set all contract fields (code, reasoning, response_format, parse_error)
4. It must be added to the tier chain in `parse_model_response`

---

## 7. EXECUTION & RUNTIME ERROR CAPTURE

### 7.1 Error Classification

| Error Type | Captured By | Classified As | Logged Fields |
|---|---|---|---|
| SyntaxError | exec_eval.py:809-816 | EXECUTION_FAILURE:syntax_error | syntax_error=str(e) |
| NameError/ImportError at load | exec_eval.py:817-825 | assembly_error=True | runtime_error=str(e) |
| NameError/ImportError during test | exec_eval.py:868-878 | assembly_error=True | runtime_error=str(e) |
| AttributeError (missing attr) | exec_eval.py:880-891 | assembly_error (if "has no attribute") | runtime_error=str(e) |
| Generic Exception at load | exec_eval.py:826-839 | assembly_error (if unresolved) | runtime_error=str(e) |
| Generic Exception during test | exec_eval.py:893 | EXECUTION_FAILURE | runtime_error=str(e) |
| No code (<10 chars) | exec_eval.py:771-775 | EXECUTION_FAILURE:no_code | reasons=["no extractable code"] |
| Rename error | exec_eval.py:791-802 | Depends on upstream cause | rename_error=True |

### 7.2 Required Improvements

1. **Rename error must trace upstream cause.** Add `rename_upstream_cause` field: "parse_failure" if parse_category indicates failure, "model_failure" if parse was clean.

2. **Assembly error must distinguish infra vs model.** Currently uses `is_unresolved` heuristic (line 828-831). This is acceptable but should be documented.

3. **No execution failure may produce reasons=[].** The `reasons` list must always contain at least one entry explaining why the case failed.

---

## 8. EVALUATION INTEGRITY PLAN

### 8.1 Invalid Input Handling

| Input State | Should Evaluation Run? | Behavior |
|---|---|---|
| code="" | exec_evaluate runs → "no extractable code" → pass=False | Correct |
| code=JSON blob (raw_fallback) | exec_evaluate runs → SyntaxError or rename_error | PROBLEM: counts as execution failure when it's a parse failure |
| reasoning="" + parse_error set | Parse gate fires → reasoning_correct=None | Correct (Fix D) |
| reasoning="" + no parse_error | Classifier runs → likely returns NO | Correct (genuine empty reasoning) |
| code extracted but assembly fails | pass=False, assembly_error=True | Correct |

### 8.2 Required Change: Raw_Fallback Code Must Not Masquerade

When `_raw_fallback=True`, the "code" is the entire raw response (usually JSON). This should NOT be fed to `exec_evaluate` as if it were Python code, because:
- It produces syntax errors that are counted as execution failures
- It produces rename errors that are counted as model failures
- Both inflate failure counts for the wrong category

**Desired behavior:** When `_raw_fallback=True`, `exec_evaluate` should immediately return:
```python
if parsed.get("_raw_fallback"):
    return _result(case_id, False, 0.0, ["raw_fallback: no code extracted"], ...)
```

This prevents raw_fallback cases from generating misleading syntax/rename errors downstream.

---

## 9. LOGGING & OBSERVABILITY DESIGN

### 9.1 Unified Event Schema (events.jsonl)

**Current fields** (retained):
```
case_id, model, condition, trial, run_id, timestamp,
pass, score, reasoning_correct, code_correct,
failure_type, category, num_attempts, elapsed_seconds
```

**Required new fields:**
```
parse_tier: int                    # 0=file_dict, 1=json_direct, ..., 4=raw_fallback
parse_repaired: bool               # True if any leniency/normalization applied
code_source: str                   # "json_code", "reconstruction", "recovery", "raw_fallback", "leg_json"
reconstruction_status: str | None  # SUCCESS, FAILED_*, None if not applicable
reconstruction_recovered: bool     # True if code recovered from failed reconstruction
content_normalized: bool           # True if file content was normalized (fences/escaping)
failure_source: str                # PRIMARY failure attribution from taxonomy
```

### 9.2 Debug Log (run.jsonl audit block)

The audit block already contains 21 fields. Add:
```
parse_tier: int
parse_repaired: bool
parse_repair_type: str | None
code_source: str
reconstruction_recovered: bool
content_normalized: bool
failure_source: str
```

### 9.3 End-to-End Trace Query

Given a case_id and condition, it must be possible to determine FROM LOGS ONLY:
1. What format the model used (response_format)
2. Which parser tier matched (parse_tier)
3. Whether any repair was applied (parse_repaired, parse_repair_type)
4. Whether reconstruction ran and what happened (reconstruction_status)
5. Whether code was recovered from a failed reconstruction (reconstruction_recovered)
6. Where the code came from (code_source)
7. Whether the code executed (execution.ran)
8. Why it failed (failure_source)
9. Whether reasoning was classified (reasoning_correct or None)
10. What the final result was (pass/fail, category)

If ANY of these cannot be determined from logs, the observability is insufficient.

---

## 10. RUN-LEVEL HEALTH MODEL

### 10.1 Run Health Status

```
HEALTHY:     All cases evaluated. No sanity warnings. Parse/recon failure rate < 10%.
DEGRADED:    All cases evaluated. Sanity warnings present. Parse/recon failure rate 10-30%.
COMPROMISED: Some cases not evaluated (crash/partial). OR parse/recon failure rate > 30%.
INVALID:     Run crashed before completion. Data may be partial.
```

### 10.2 Health Signals

| Signal | Trigger | Action |
|---|---|---|
| parse_failure_rate > 10% | More than 10% of cases hit raw_fallback | Tag run DEGRADED. Log warning. |
| reconstruction_failure_rate > 10% | More than 10% of cases lost code to recon failure | Tag run DEGRADED. |
| reconstruction_recovery_rate > 5% | More than 5% of cases needed content normalization | Tag run DEGRADED (data quality concern). |
| ran_rate < 50% | Less than 50% of cases executed code | Tag run COMPROMISED. |
| pass_rate == 0 with > 10 cases | Zero passes | Tag run COMPROMISED. |
| partial_completion | Run crashed before all cases | Tag run INVALID for missing cases. |

### 10.3 Metadata Fields

```
metadata.json:
  "run_health": "HEALTHY" | "DEGRADED" | "COMPROMISED" | "INVALID",
  "health_signals": [
    {"signal": "high_parse_failure_rate", "value": 0.15, "threshold": 0.10},
    ...
  ],
  "sanity_warnings": [...],
  "cases_attempted": 116,
  "cases_completed": 116,
```

---

## 11. SILENT FAILURE ELIMINATION AUDIT

| # | File:Function | Current Behavior | Required Change |
|---|---|---|---|
| 1 | `parse.py:120` `_try_json_lenient` | `except Exception: pass` | Narrow to `(json.JSONDecodeError, TypeError, re.error)`. Log unexpected exceptions. |
| 2 | `parse.py:251` `_try_file_dict_lenient` | `except Exception: pass` | Same. |
| 3 | `parse.py:354-360` raw_fallback | Code=raw, reasoning="" | Add `code_source="raw_fallback"` to output. |
| 4 | `execution.py:186-190` event emission | `except Exception: warning` | Count lost events. Add `events_lost` to run metadata. |
| 5 | `execution.py:209-211` code None→"" | Now explicit. Was silent via setdefault. | FIXED. |
| 6 | `evaluator.py:571` `identified_correct_issue` | `classify["reasoning_correct"] or False` — converts None to False | This is intentional (backward compat). But the `or False` hides None. Add comment. |
| 7 | `exec_eval.py` raw_fallback code | JSON blob enters exec_evaluate as "code" → syntax/rename errors | Should short-circuit when `_raw_fallback=True`. |

---

## 12. VALIDATION STRATEGY

### 12.1 Test Matrix

| Test | Input | Expected Classification | Expected Logging |
|---|---|---|---|
| Valid JSON, code key | `{"reasoning": "...", "code": "def f(): pass"}` | parse_tier=2 (json_direct), failure_source=depends on code quality | No warnings |
| Valid JSON, files key | `{"reasoning": "...", "files": {"a.py": "def f(): pass"}}` | parse_tier=0 (file_dict), reconstruction runs | No warnings |
| Malformed JSON, code key, literal newlines | `{"reasoning": "...", "code": "def f():\n    pass"}` | parse_tier=3 (json_lenient), parse_repaired=True | Warning: lenient parser used |
| Malformed JSON, files key, literal newlines | `{"reasoning": "...", "files": {"a.py": "def f():\n    pass"}}` | parse_tier=1 (file_dict_lenient), parse_repaired=True | Warning: lenient file-dict parser used |
| File content with markdown fences | Valid JSON, file value has ` ```python ... ``` ` | reconstruction SUCCESS after normalization, content_normalized=True | Info: content normalized |
| File content with escaped \\n | Valid JSON, file value has `def f():\\n    pass` | reconstruction SUCCESS after unescape, content_normalized=True | Info: content normalized |
| All files UNCHANGED | `{"files": {"a.py": "UNCHANGED", "b.py": "UNCHANGED"}}` | reconstruction SUCCESS, changed_files=empty, code="" | Info: all files unchanged |
| Empty response | `""` | parse_tier=N/A, failure_source=PARSE_FAILURE | SEVERE warning |
| Runtime exception in model code | Valid Python that raises | failure_source=MODEL_FAILURE:runtime_error | runtime_error field set |
| Rename error from parse failure | Raw_fallback JSON blob → rename | failure_source=PARSE_FAILURE (not MODEL_FAILURE) | Both parse_error and rename logged, but failure_source=PARSE |
| Genuine rename error | Clean parse, model defines wrong function | failure_source=MODEL_FAILURE:rename_error | rename_error=True |
| Classifier exception | LLM call fails | reasoning_correct=None, failure_source unchanged | classify_parse_error set |

---

## 13. IMPLEMENTATION PLAN (ORDERED)

### Phase 0 (P0) — Critical Stabilization (DONE in previous pass)

Already implemented:
- RC-1: Markdown fence stripping in reconstructor
- RC-2: Escaped newline normalization in reconstructor
- RC-3: Lenient file-dict parser
- RC-4: All-UNCHANGED assertion removal
- RC-5: Reconstruction recovery path
- RC-6: Sanity guard downgrade
- AI-1: code=None normalization

### Phase 1 (P1) — Observability Layer

| # | Change | Files | Risk |
|---|---|---|---|
| P1-1 | Add `parse_tier`, `parse_repaired`, `parse_repair_type` to parse_model_response output | parse.py | LOW — adds fields only |
| P1-2 | Add `code_source` field to parsed dict in execution.py | execution.py | LOW — adds field only |
| P1-3 | Add `content_normalized`, `normalization_log` to ReconstructionResult | reconstructor.py | LOW — adds fields only |
| P1-4 | Add `failure_source` attribution to exec_evaluate result | exec_eval.py | MEDIUM — new logic to attribute |
| P1-5 | Add new fields to events.jsonl emission | execution.py | LOW — extends event dict |
| P1-6 | Add new fields to run.jsonl audit block | execution.py | LOW — extends audit dict |
| P1-7 | Add run health computation to metadata | runner.py | LOW — post-run computation |

### Phase 2 (P2) — Hardening

| # | Change | Files |
|---|---|---|
| P2-1 | Short-circuit raw_fallback code in exec_evaluate | exec_eval.py |
| P2-2 | Narrow exception catches in lenient parsers | parse.py |
| P2-3 | Add `rename_upstream_cause` field | exec_eval.py |
| P2-4 | Count lost events in event emission | execution.py |
| P2-5 | Add `reasons` non-empty assertion to all _result calls | exec_eval.py |

### Phase 3 (P3) — Verification

| # | Change |
|---|---|
| P3-1 | End-to-end trace test: given a case, verify all 10 trace questions answerable from logs |
| P3-2 | Failure attribution test: verify failure_source precedence rules |
| P3-3 | Run health computation test: verify degraded/compromised triggers |
| P3-4 | Parser symmetry test: verify both code and files formats have equivalent coverage |

### Rollout Validation

After each phase:
1. Run full test suite (must pass)
2. Run canary (3 cases, 2 models) — verify new fields populated
3. Verify no behavior change from observability-only additions (P1)
4. Verify behavior changes are intentional (P2)
