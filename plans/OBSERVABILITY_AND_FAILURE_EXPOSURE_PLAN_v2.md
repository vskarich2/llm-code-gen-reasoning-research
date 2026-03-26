# System-Wide Failure Exposure and Observability Plan

**Version:** v2
**Date:** 2026-03-26
**Status:** PLAN ONLY — No implementation.
**Supersedes:** OBSERVABILITY_AND_FAILURE_EXPOSURE_PLAN.md (v1)
**Scope:** All parsing, reconstruction, execution, evaluation, metrics, and logging paths.

---

## CHANGELOG (v1 → v2)

| Addition | What | Why v1 Was Incomplete |
|---|---|---|
| Section 3 | Empty code disambiguation: `code_present` + `code_empty_reason` | v1 allowed `code==""` to mean 5 different things with no way to distinguish them |
| Section 4 | Recovery vs transformation distinction | v1 conflated "fixing model's broken JSON" with "restructuring valid content" |
| Section 5 | SYSTEM_FAILURE vs INFRA_FAILURE in taxonomy | v1 had no category for pipeline bugs or I/O failures |
| Section 6 | Case validity model: valid/degraded/invalid | v1 allowed invalid cases (raw_fallback JSON blobs) to enter metrics |
| Section 7 | Metric denominator rules with explicit inclusion/exclusion | v1 did not specify which cases count toward which metrics |
| Section 8 | System invariants with enforcement | v1 had no invariant checking |
| Section 9 | Data lineage tracking | v1 could not reconstruct what happened to a case without re-running |
| Section 10 | Invalid data boundary: when to stop processing | v1 continued processing hopeless cases (raw_fallback JSON as code) |

---

## 1. GLOBAL FAILURE MODEL

### 1.1 Failure Classes (Complete)

| Class | Subtype | Trigger | Desired Behavior |
|---|---|---|---|
| **PARSE_FAILURE** | json_invalid | json.loads fails, no lenient tier matches | Classify. Log tier chain. |
| **PARSE_FAILURE** | json_malformed_files | Files-format JSON with literal newlines | Lenient tier catches. Tag as recovered. |
| **PARSE_FAILURE** | json_malformed_code | Code-format JSON with literal newlines | _try_json_lenient catches. Tag as recovered. |
| **PARSE_FAILURE** | empty_response | Model returned nothing | code_present=False, code_empty_reason=model_no_output |
| **PARSE_FAILURE** | raw_fallback | No tier matched, entire response used as "code" | case_validity=INVALID. Must NOT enter exec_evaluate as code. |
| **RECONSTRUCTION_FAILURE** | missing_files | Model omitted expected files | code_present=False, code_empty_reason=reconstruction_failure |
| **RECONSTRUCTION_FAILURE** | syntax_errors | AST fails on content | Recovery via normalization. If still fails: code_empty_reason=reconstruction_failure |
| **RECONSTRUCTION_FAILURE** | empty_files | Empty file content | code_present=False, code_empty_reason=reconstruction_failure |
| **RECONSTRUCTION_FAILURE** | all_unchanged | All files marked UNCHANGED | code_present=False, code_empty_reason=all_unchanged |
| **MODEL_FAILURE** | syntax_error | Model code has Python syntax error | Genuine model failure. pass=False. |
| **MODEL_FAILURE** | runtime_error | Model code crashes at runtime | Genuine model failure. pass=False. |
| **MODEL_FAILURE** | invariant_fail | Code runs but fails invariant test | Genuine model failure. pass=False. |
| **MODEL_FAILURE** | rename_error | Model defined wrong function name (genuine) | Genuine model failure. pass=False. |
| **EVALUATION_FAILURE** | classifier_exception | LLM classifier call fails | reasoning_correct=None. Does not affect pass/fail. |
| **EVALUATION_FAILURE** | classifier_parse_error | Classifier output malformed | reasoning_correct=None. |
| **EVALUATION_FAILURE** | reasoning_gated | Parse gate blocks classification | reasoning_correct=None. Upstream cause is PARSE_FAILURE. |
| **SYSTEM_FAILURE** | contract_violation | Internal state violates invariant | Raise error. Log. Mark case invalid. |
| **SYSTEM_FAILURE** | pipeline_bug | Code logic error (e.g., old assertion crash) | Raise error. Log. Mark run degraded. |
| **INFRA_FAILURE** | event_emission_failure | events.jsonl write fails | Log warning. Count lost events. Mark run degraded. |
| **INFRA_FAILURE** | log_write_failure | run.jsonl write fails | Already tracked by RunLogger.writes_failed. Mark run degraded. |
| **INFRA_FAILURE** | api_failure | LLM API call fails | Exception propagated. Case not evaluated. |

### 1.2 Silent Failure Inventory

| # | File:Line | Current Behavior | Required Change |
|---|---|---|---|
| 1 | parse.py:120 | `except Exception: pass` | Narrow to `(json.JSONDecodeError, TypeError, re.error)`. Log unexpected. |
| 2 | parse.py:251 | `except Exception: pass` | Same. |
| 3 | parse.py:354-360 | raw_fallback: code=raw, reasoning="" | Mark case_validity=INVALID. Do NOT feed to exec_evaluate as code. |
| 4 | execution.py:186-190 | Event emission swallowed | Count lost events. Add events_lost to metadata. |
| 5 | evaluator.py:571 | `classify["reasoning_correct"] or False` | Converts None→False for backward compat field. Add comment. Not a bug. |
| 6 | exec_eval.py:828 | `except Exception` catch-all | Classify via is_unresolved heuristic. Acceptable. |

---

## 2. STAGE-BY-STAGE CONTRACT DESIGN

### Stage 1: Model Output → Parser

**Input:** `raw_output: str`

**Output contract:**
```
{
    "code": str,                     # MUST be str. "" if not extracted.
    "code_present": bool,            # True if meaningful code was extracted.
    "code_empty_reason": str | None, # Set ONLY when code_present=False.
    "reasoning": str,                # MUST be str. "" if not extracted.
    "files": dict | None,
    "confidence": float | None,
    "parse_error": str | None,
    "response_format": str,          # MUST be set.
    "_raw_fallback": bool,
    "parse_tier": int,               # 0=file_dict, 0b=file_dict_lenient, 1=json_direct, etc.
    "parse_repaired": bool,          # True if lenient/repair was used.
    "parse_repair_type": str | None, # "lenient_json", "lenient_file_dict", None.
    "data_lineage": list[str],       # Ordered list of transformations applied.
}
```

**Invalid states (must raise ValueError):**
- `code` is None
- `response_format` is missing
- `_raw_fallback=True` AND `parse_error` is None
- `code_present=True` AND code is empty/whitespace
- `code_present=False` AND `code_empty_reason` is None

### Stage 2: Parser → Reconstruction

**Input:** `parsed["files"]` is non-empty dict with str values.

**Output:**
```
ReconstructionResult:
    status: str,
    files: dict[str, str],
    changed_files: set[str],
    missing_files: set[str],
    extra_files: set[str],
    syntax_errors: dict[str, str],
    content_normalized: bool,
    normalization_log: list[str],    # Per-file normalization actions.
    recovery_applied: bool,          # True if content normalization fixed AST errors.
    recovery_types: list[str],       # ["fence_stripped", "newlines_unescaped"]
    transformation_applied: bool,    # Always False in reconstruction (no structural changes).
    transformation_types: list[str], # Always [].
```

**Invalid states (must raise RuntimeError):**
- `status=="SUCCESS"` AND `files` is empty
- `status=="FAILED_MISSING_FILES"` AND `missing_files` is empty

### Stage 3: Reconstruction → Execution Handoff

**Output to exec_evaluate:**
```
parsed dict must contain:
    "code": str,
    "code_present": bool,
    "code_empty_reason": str | None,
    "code_source": str,              # "json_code_field", "reconstruction", "reconstruction_recovery",
                                     # "fallback_parser", "leg_json", "NONE"
    "_raw_fallback": bool,
    "_reconstruction_status": str | None,
    "_reconstruction_recovered": bool,
    "case_validity": str,            # "valid", "degraded", "invalid"
    "data_lineage": list[str],
```

**case_validity assignment rules:**
```
if _raw_fallback:
    case_validity = "invalid"
elif _reconstruction_recovered:
    case_validity = "degraded"
elif parse_repaired:
    case_validity = "degraded"
elif code_present:
    case_validity = "valid"
else:
    case_validity = "invalid"
```

### Stage 4: Execution → Evaluation

**Output from exec_evaluate:**
```
{
    "pass": bool,
    "score": float,
    "reasons": list[str],           # MUST be non-empty when pass=False.
    "failure_modes": list[str],
    "execution": dict,
    "_extracted_code": str,
    "_assembled_code": str,
    "failure_source": str,          # PRIMARY failure from taxonomy.
    "failure_source_detail": str,   # Subtype.
}
```

### Stage 5: Evaluation → Events/Logging

**events.jsonl required fields:**
```
{
    # Identity
    "case_id": str, "model": str, "condition": str, "trial": int, "run_id": str, "timestamp": str,

    # Results
    "pass": bool, "score": float, "reasoning_correct": bool | None, "code_correct": bool,
    "failure_type": str | None, "category": str, "num_attempts": int, "elapsed_seconds": float,

    # Observability (NEW — all required)
    "code_present": bool,
    "code_empty_reason": str | None,
    "code_source": str,
    "case_validity": str,           # "valid", "degraded", "invalid"
    "parse_tier": int,
    "parse_repaired": bool,
    "recovery_applied": bool,
    "recovery_types": list[str],
    "reconstruction_status": str | None,
    "reconstruction_recovered": bool,
    "content_normalized": bool,
    "failure_source": str,
    "failure_source_detail": str,
}
```

---

## 3. EMPTY CODE DISAMBIGUATION

### 3.1 Fields

```json
{
    "code_present": true | false,
    "code_empty_reason": null | one of:
        "model_no_output"           // Model returned empty or whitespace-only response.
        "parse_failure"             // JSON could not be parsed. No code field found.
        "reconstruction_failure"    // Reconstruction failed. Code in files dict but unrecoverable.
        "all_unchanged"             // Model marked all files UNCHANGED. No code changes.
        "filtered_invalid"          // Raw_fallback produced JSON blob. Filtered as invalid.
        "no_code_field"             // JSON parsed but no "code" or "files" key present.
}
```

### 3.2 Assignment Rules

| Condition | code_present | code_empty_reason |
|---|---|---|
| code is non-empty string with >= 10 chars | True | None |
| code is "" AND model response was empty | False | model_no_output |
| code is "" AND parse hit raw_fallback | False | filtered_invalid |
| code is "" AND reconstruction returned FAILED_* | False | reconstruction_failure |
| code is "" AND all files UNCHANGED | False | all_unchanged |
| code is "" AND JSON parsed but no code/files key | False | no_code_field |
| code is "" AND parse_error is set (any non-raw tier) | False | parse_failure |

### 3.3 Propagation

`code_present` and `code_empty_reason` MUST be set:
- In parser output (for parse-level failures)
- In execution.py after reconstruction (for reconstruction-level failures)
- Before passing to exec_evaluate

### 3.4 Invariant

```
if code_present == False:
    assert code_empty_reason is not None
if code_present == True:
    assert code_empty_reason is None
    assert len(code.strip()) >= 10
```

---

## 4. RECOVERY VS TRANSFORMATION DISTINCTION

### 4.1 Definitions

**RECOVERY**: Fixing malformed model output to extract the intended content. The model INTENDED to produce X; the output is a corrupted version of X; recovery restores X.

Examples:
- Stripping markdown fences that model wrapped around code in JSON string value
- Unescaping `\\n` to real newlines when model double-escaped
- Lenient JSON parsing to handle literal newlines in strings
- Extracting code from `FAILED_SYNTAX_ERRORS` reconstruction after normalization

**TRANSFORMATION**: Altering the STRUCTURE or MEANING of valid content. The content is not corrupted — it is restructured by the system.

Examples:
- Multi-file assembly (prepending original files + appending model code)
- Stripping local imports from code before execution
- Concatenating multiple file contents into single string

### 4.2 Fields

```json
{
    "recovery_applied": bool,
    "recovery_types": [
        "fence_stripped",           // Markdown fences removed from file content
        "newlines_unescaped",       // \\n replaced with real newlines
        "lenient_json_parsed",      // Lenient JSON parser used instead of strict
        "lenient_file_dict_parsed", // Lenient file-dict parser used
        "reconstruction_recovery"   // Code recovered from failed reconstruction
    ],
    "transformation_applied": bool,
    "transformation_types": [
        "multi_file_assembly",      // Original files prepended to model code
        "import_stripping",         // Local imports removed
        "file_concatenation"        // Multiple file contents joined
    ]
}
```

### 4.3 Rules

1. Recovery implies the model output was malformed. The case is `case_validity="degraded"`.
2. Transformation is standard pipeline behavior. It does NOT degrade case validity.
3. Recovery and transformation are independent — a case can have both.
4. Every recovery type maps to a specific model output defect.
5. Every transformation type maps to a specific pipeline processing step.
6. Both are logged in `data_lineage`.

---

## 5. FAILURE TAXONOMY (COMPLETE — 8 Categories)

### 5.1 Categories

```
PARSE_FAILURE          // JSON parsing failed. Code not extractable.
RECONSTRUCTION_FAILURE // JSON parsed but reconstruction lost code.
MODEL_FAILURE          // Code extracted and executed but failed tests.
EVALUATION_FAILURE     // Execution succeeded but reasoning classifier failed.
SYSTEM_FAILURE         // Bug in pipeline logic. Contract violation. Invalid internal state.
INFRA_FAILURE          // I/O failure, API failure, event emission failure.
SUCCESS                // Code correct. Reasoning classified.
NOT_EVALUATED          // Case not reached (run crashed before this case).
```

### 5.2 SYSTEM_FAILURE (New)

**Trigger:** Internal invariant violation, contract violation, impossible state.

**Examples:**
- code_present=True but code is empty (invariant violation)
- reconstruction status=SUCCESS but files dict is empty
- failure_source not set at end of pipeline
- case_validity not set at end of pipeline

**Behavior:** Raise error. Log full state. Mark case as `case_validity="invalid"`.

**Counting:** SYSTEM_FAILURE cases MUST NOT count as MODEL_FAILURE. They are infrastructure bugs, not model quality signals.

### 5.3 INFRA_FAILURE (New)

**Trigger:** External system failure not caused by model output or pipeline logic.

**Examples:**
- events.jsonl write failed (OS error)
- run.jsonl write failed
- LLM API call failed (network, rate limit, timeout)
- File read failed during case loading

**Behavior:** Log warning. Count occurrence. Mark run as degraded if threshold exceeded.

**Counting:** INFRA_FAILURE cases MUST NOT count toward any model-quality metric. If an INFRA_FAILURE prevents evaluation, the case is `case_validity="invalid"` and excluded from all rate computations.

### 5.4 Attribution Precedence (Strict)

```
1. SYSTEM_FAILURE > everything    (pipeline bug)
2. INFRA_FAILURE > model path     (external failure)
3. PARSE_FAILURE > downstream     (can't parse → can't execute)
4. RECONSTRUCTION_FAILURE > exec  (can't reconstruct → can't execute)
5. EVALUATION_FAILURE alongside   (does not override execution result)
6. MODEL_FAILURE                  (genuine model quality signal)
7. SUCCESS                        (everything worked)
8. NOT_EVALUATED                  (run incomplete)
```

### 5.5 Mutual Exclusivity Rule

Every case has exactly ONE `failure_source`. If multiple failures occur, the HIGHEST precedence one is recorded. Lower-precedence failures are recorded in `failure_source_secondary` (list).

---

## 6. CASE VALIDITY MODEL

### 6.1 States

```
VALID:
    - Clean parse OR lenient parse (both produce usable code)
    - Code correctly extracted (code_present=True)
    - Execution attempted (or code="" from all_unchanged — legitimate model choice)
    - No system/infra failure

DEGRADED:
    - Recovery applied (fence stripping, newline unescape, reconstruction recovery)
    - Lenient parsing used
    - Partial signal preserved (code extracted but from imperfect source)
    - Still usable for analysis WITH explicit annotation

INVALID:
    - Raw_fallback used (JSON blob as "code")
    - Unrecoverable parse failure (no code extracted)
    - System failure (contract violation)
    - Infra failure (API down, I/O error)
    - Missing required fields
    - Case not evaluated (run crashed)
```

### 6.2 Assignment Rules

```python
def compute_case_validity(parsed, ev):
    # INVALID conditions (checked first)
    if parsed.get("_raw_fallback"):
        return "invalid"
    if ev.get("failure_source") in ("SYSTEM_FAILURE", "INFRA_FAILURE", "NOT_EVALUATED"):
        return "invalid"
    if not parsed.get("code_present") and parsed.get("code_empty_reason") in (
        "parse_failure", "model_no_output", "filtered_invalid"
    ):
        return "invalid"

    # DEGRADED conditions
    if parsed.get("recovery_applied"):
        return "degraded"
    if parsed.get("parse_repaired"):
        return "degraded"
    if parsed.get("_reconstruction_recovered"):
        return "degraded"

    # VALID
    return "valid"
```

### 6.3 Critical Rule

**INVALID cases MUST NOT be included in primary metrics (pass_rate, LEG_rate, true_success_rate, lucky_fix_rate, true_failure_rate).**

INVALID cases ARE included in:
- `parse_failure_rate` (as numerator)
- `case_validity_distribution` (as count)
- `total_cases` (as denominator for parse/validity rates)

DEGRADED cases ARE included in primary metrics but flagged:
- `degraded_rate` is reported alongside primary metrics
- If `degraded_rate > 20%` for any condition, primary metrics carry a warning

---

## 7. METRIC DENOMINATOR RULES

### 7.1 Definitions

```
N_total      = all cases attempted for a condition
N_valid      = cases with case_validity == "valid"
N_degraded   = cases with case_validity == "degraded"
N_invalid    = cases with case_validity == "invalid"
N_evaluated  = N_valid + N_degraded  (cases that produced a real execution result)
```

Identities (invariants):
```
N_total == N_valid + N_degraded + N_invalid
```

### 7.2 Per-Metric Rules

| Metric | Numerator | Denominator | Includes DEGRADED? | Includes INVALID? |
|---|---|---|---|---|
| pass_rate | count(pass==True AND case_validity in {valid, degraded}) | N_evaluated | YES | **NO** |
| LEG_rate | count(reasoning_correct AND NOT code_correct AND case_validity in {valid, degraded}) | N_evaluated | YES | **NO** |
| true_success_rate | count(reasoning_correct AND code_correct AND ...) | N_evaluated | YES | **NO** |
| lucky_fix_rate | count(NOT reasoning_correct AND code_correct AND ...) | N_evaluated | YES | **NO** |
| true_failure_rate | count(NOT reasoning_correct AND NOT code_correct AND ...) | N_evaluated | YES | **NO** |
| parse_failure_rate | count(failure_source == PARSE_FAILURE) | N_total | YES | **YES** |
| reconstruction_failure_rate | count(failure_source == RECONSTRUCTION_FAILURE) | N_total | YES | **YES** |
| case_validity_valid_rate | N_valid | N_total | N/A | N/A |
| case_validity_degraded_rate | N_degraded | N_total | N/A | N/A |
| case_validity_invalid_rate | N_invalid | N_total | N/A | N/A |
| recovery_rate | count(recovery_applied) | N_total | N/A | N/A |

### 7.3 Mandatory Reporting

Every results table MUST include: `N_total`, `N_valid`, `N_degraded`, `N_invalid`, `N_evaluated`.

**Hard rule:** If `N_invalid / N_total > 20%` for any condition, the condition's primary metrics are flagged as `LOW_CONFIDENCE` and must include this warning in any report.

**Hard rule:** Cross-condition comparison is INVALID if `N_invalid` rates differ by > 15pp between conditions.

---

## 8. SYSTEM INVARIANTS

### 8.1 Invariant List

Every invariant MUST be checked at the point specified. Violation MUST raise an error and log the full state.

| # | Invariant | Check Point | What It Prevents |
|---|---|---|---|
| I1 | `code` is always `str`, never `None` | After `_build_parsed_response` | Type confusion downstream |
| I2 | `code_present=False` → `code_empty_reason is not None` | After code_present is set | Ambiguous empty code |
| I3 | `code_present=True` → `code_empty_reason is None` | After code_present is set | Contradictory state |
| I4 | `code_present=True` → `len(code.strip()) >= 10` | After code_present is set | Labeling empty/trivial code as present |
| I5 | `_raw_fallback=True` → `parse_error is not None` | In raw_fallback branch | Raw fallback without error signal |
| I6 | `_raw_fallback=True` → `case_validity == "invalid"` | After case_validity is computed | Invalid data entering metrics |
| I7 | `failure_source == PARSE_FAILURE` → `execution.ran == False` | After failure_source is set | Parse failure counted as execution |
| I8 | `pass == True` → `failure_source == "SUCCESS"` | After all evaluation | Passing case with failure attribution |
| I9 | `pass == True` → `case_validity in ("valid", "degraded")` | After all evaluation | Invalid case counted as pass |
| I10 | `reconstruction_recovered=True` → `reconstruction_status != "SUCCESS"` | After reconstruction | Recovery without failure is contradictory |
| I11 | `case_validity == "invalid"` → `pass == False` | After case_validity computed | Invalid case counted as success |
| I12 | `failure_source` is set for every case | End of pipeline | Missing attribution |
| I13 | `case_validity` is set for every case | End of pipeline | Missing validity |
| I14 | `data_lineage` is non-empty for every case | End of pipeline | Missing trace |
| I15 | `reasons` is non-empty when `pass == False` | After exec_evaluate | Silent failure |
| I16 | `N_valid + N_degraded + N_invalid == N_total` | Metric computation | Denominator leak |
| I17 | `recovery_applied=True` → `len(recovery_types) > 0` | After recovery tracking | Recovery without type |
| I18 | `transformation_applied=True` → `len(transformation_types) > 0` | After transformation tracking | Transformation without type |

### 8.2 Enforcement

```python
def check_invariants(parsed, ev):
    """Called after evaluate_output, before logging. Raises on violation."""
    violations = []

    if not isinstance(parsed.get("code"), str):
        violations.append("I1: code is not str")
    if not parsed.get("code_present") and parsed.get("code_empty_reason") is None:
        violations.append("I2: code_present=False but code_empty_reason is None")
    if parsed.get("code_present") and parsed.get("code_empty_reason") is not None:
        violations.append("I3: code_present=True but code_empty_reason is set")
    # ... all invariants ...

    if violations:
        raise SystemFailure(
            f"INVARIANT VIOLATIONS ({len(violations)}): {violations}. "
            f"case={parsed.get('case_id')}, condition={parsed.get('condition')}"
        )
```

---

## 9. DATA LINEAGE TRACKING

### 9.1 Specification

Every case carries a `data_lineage` list that records, in order, every processing step applied to the data.

```json
{
    "data_lineage": [
        "raw_output_received",
        "parse_tier_0a_file_dict_attempted",
        "parse_tier_0a_failed",
        "parse_tier_0b_file_dict_lenient_attempted",
        "parse_tier_0b_matched",
        "parse_repair:lenient_file_dict",
        "reconstruction_attempted",
        "content_normalized:fence_stripped:a.py",
        "content_normalized:newlines_unescaped:b.py",
        "reconstruction_status:SUCCESS",
        "code_extracted:reconstruction",
        "transformation:import_stripping",
        "transformation:multi_file_assembly",
        "execution_attempted",
        "execution_completed:pass=True",
        "evaluation_attempted",
        "evaluation_completed:reasoning_correct=True"
    ]
}
```

### 9.2 Rules

1. Every stage appends to lineage. No stage may clear it.
2. Lineage must be sufficient to reconstruct what happened WITHOUT re-running.
3. Lineage is stored in run.jsonl audit block.
4. Lineage entries follow format: `stage:action:detail` (detail optional).

### 9.3 Required Lineage Events

| Event | When |
|---|---|
| `raw_output_received` | Always (first entry) |
| `parse_tier_N_attempted` | Each tier tried |
| `parse_tier_N_matched` | Tier that succeeded |
| `parse_tier_N_failed` | Each tier that failed (optional — only if logging verbosity is high) |
| `parse_repair:TYPE` | When lenient parsing or repair is used |
| `reconstruction_attempted` | When reconstruction branch is entered |
| `content_normalized:TYPE:FILE` | Per-file normalization |
| `reconstruction_status:STATUS` | After reconstruction completes |
| `reconstruction_recovery_attempted` | When recovery from FAILED_SYNTAX_ERRORS is tried |
| `code_extracted:SOURCE` | Where code came from |
| `code_empty:REASON` | When code_present=False |
| `case_validity:STATE` | After validity is computed |
| `transformation:TYPE` | Each transformation applied |
| `execution_attempted` | Before exec_evaluate |
| `execution_completed:RESULT` | After exec_evaluate |
| `evaluation_attempted` | Before llm_classify |
| `evaluation_completed:RESULT` | After llm_classify |

---

## 10. INVALID DATA BOUNDARY

### 10.1 When to STOP Processing

| Condition | Action | Rationale |
|---|---|---|
| `_raw_fallback=True` | Do NOT pass to exec_evaluate. Set pass=False, failure_source=PARSE_FAILURE. | JSON blob is not code. Executing it produces misleading syntax/rename errors. |
| Model response is empty | Do NOT attempt reconstruction or execution. Set pass=False. | Nothing to evaluate. |
| `code_present=False` after all recovery attempts | Do NOT pass to exec_evaluate. | No code = no execution. |

### 10.2 When to Allow DEGRADED Continuation

| Condition | Action | Rationale |
|---|---|---|
| Lenient parse succeeded | Continue. Tag as degraded. | Code was extractable, just from malformed JSON. |
| Content normalized (fences/escaping) | Continue. Tag as degraded. | Code exists under formatting artifacts. |
| Reconstruction recovery succeeded | Continue. Tag as degraded. | Code was recoverable from failed reconstruction. |

### 10.3 When to Mark INVALID

| Condition | case_validity | code_empty_reason |
|---|---|---|
| Raw_fallback fired | invalid | filtered_invalid |
| Empty model response | invalid | model_no_output |
| Reconstruction failed AND recovery failed | invalid | reconstruction_failure |
| Parse failure (no tier matched except raw_fallback) | invalid | parse_failure |
| System failure (invariant violation) | invalid | system_failure |
| Infra failure (API down, I/O error) | invalid | infra_failure |

---

## 11. LOGGING COMPLETENESS CHECKLIST

For ANY case, logs MUST answer all 10 questions:

| # | Question | Field(s) That Answer It |
|---|---|---|
| 1 | Where did the code come from? | `code_source`, `data_lineage` |
| 2 | Was parsing repaired? | `parse_repaired`, `parse_repair_type`, `data_lineage` |
| 3 | Was content transformed? | `transformation_applied`, `transformation_types`, `data_lineage` |
| 4 | Did reconstruction fail? | `reconstruction_status`, `_reconstruction_error` |
| 5 | Was recovery applied? | `recovery_applied`, `recovery_types`, `_reconstruction_recovered` |
| 6 | Why did execution fail? | `failure_source`, `failure_source_detail`, `reasons` |
| 7 | Is this a model failure or system/infra failure? | `failure_source` (MODEL vs SYSTEM vs INFRA) |
| 8 | Is this case valid, degraded, or invalid? | `case_validity` |
| 9 | Why is code empty (if empty)? | `code_present`, `code_empty_reason` |
| 10 | Can I reconstruct what happened without re-running? | `data_lineage` (ordered step list) |

If ANY question cannot be answered from a single case's log record, the plan is incomplete.

---

## 12. RUN-LEVEL HEALTH MODEL

### 12.1 Health States

```
HEALTHY:
    - All cases evaluated (N_total == expected)
    - case_validity_invalid_rate < 5%
    - recovery_rate < 10%
    - No SYSTEM_FAILURE or INFRA_FAILURE

DEGRADED:
    - All cases evaluated
    - case_validity_invalid_rate 5-20% OR recovery_rate 10-30%
    - OR any INFRA_FAILURE occurred (event loss)

COMPROMISED:
    - case_validity_invalid_rate > 20%
    - OR ran_rate < 50%
    - OR any SYSTEM_FAILURE occurred

INVALID:
    - Run crashed before completion
    - OR N_total < expected (missing cases)
```

### 12.2 Metadata

```json
{
    "run_health": "HEALTHY|DEGRADED|COMPROMISED|INVALID",
    "health_signals": [
        {"signal": "...", "value": 0.15, "threshold": 0.10, "status": "WARNING"}
    ],
    "cases_attempted": 116,
    "cases_completed": 116,
    "cases_valid": 108,
    "cases_degraded": 5,
    "cases_invalid": 3,
    "events_lost": 0,
    "system_failures": 0,
    "infra_failures": 0,
    "sanity_warnings": [...]
}
```

---

## 13. IMPLEMENTATION PLAN (ORDERED)

### Phase 1 (P1) — Core Schema + Invariants

| # | Change | Files | Risk |
|---|---|---|---|
| P1-1 | Add `code_present`, `code_empty_reason` to parser output and execution handoff | parse.py, execution.py | LOW |
| P1-2 | Add `recovery_applied`, `recovery_types`, `transformation_applied`, `transformation_types` | reconstructor.py, execution.py, exec_eval.py | LOW |
| P1-3 | Add `case_validity` computation | execution.py | LOW |
| P1-4 | Add `failure_source`, `failure_source_detail` attribution | exec_eval.py, execution.py | MEDIUM |
| P1-5 | Add `data_lineage` accumulation | parse.py, reconstructor.py, execution.py | LOW |
| P1-6 | Add invariant checking function | New file: invariants.py or inline | MEDIUM |
| P1-7 | Add all new fields to events.jsonl emission | execution.py | LOW |
| P1-8 | Add all new fields to run.jsonl audit block | execution.py | LOW |

### Phase 2 (P2) — Invalid Data Boundary

| # | Change | Files |
|---|---|---|
| P2-1 | Short-circuit raw_fallback in exec_evaluate (do not execute JSON blobs as code) | exec_eval.py |
| P2-2 | Add SYSTEM_FAILURE and INFRA_FAILURE to failure taxonomy | Throughout |
| P2-3 | Add event emission failure counting | execution.py |
| P2-4 | Add run health computation | runner.py |

### Phase 3 (P3) — Metric Rules

| # | Change | Files |
|---|---|---|
| P3-1 | Update metric computation to use N_evaluated (exclude INVALID) | live_metrics.py, scripts/ |
| P3-2 | Add mandatory N_valid/N_degraded/N_invalid columns to all reports | scripts/ |
| P3-3 | Add cross-condition N_invalid gap warning | scripts/ |

### Phase 4 (P4) — Verification

| # | Test |
|---|---|
| P4-1 | Invariant test: every invariant violation detected |
| P4-2 | Case validity test: correct assignment for all scenarios |
| P4-3 | Lineage test: all 10 questions answerable from logs |
| P4-4 | Metric test: INVALID cases excluded, denominators correct |
| P4-5 | Failure attribution test: precedence rules enforced |
| P4-6 | Run health test: thresholds trigger correct health state |

### Rollout Validation

After each phase:
1. Full test suite passes
2. Canary run (3 cases, 2 models) — verify new fields populated
3. No behavioral change from observability additions (P1)
4. Intentional behavioral changes verified (P2, P3)
