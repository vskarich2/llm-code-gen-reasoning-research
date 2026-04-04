# Full-System Forensic Audit — 2026-04-04

## 1. EXECUTIVE SUMMARY

### Top 10 Critical Failures

| # | Severity | Issue | File | Impact |
|---|----------|-------|------|--------|
| 1 | **CRITICAL** | events.jsonl in APPEND mode causes duplicate events on retry | logging_core.py:255 | Corrupted WAL, validation fails, workers crash |
| 2 | **CRITICAL** | Logger not passed to oracle in retry_v2.py | retry_v2.py:452 | Oracle LLM calls in retry chains silently unlogged |
| 3 | **CRITICAL** | finalize() not in try/finally — crash loses metrics.json | runner.py:558-712 | Incomplete run undetected, no validation |
| 4 | **HIGH** | oracle.timeout parsed but never used | experiment_config.py:152 | Oracle calls have no timeout enforcement |
| 5 | **HIGH** | AST checker exceptions logged at DEBUG only | ast_eval.py:160-177 | Production checker crashes invisible |
| 6 | **HIGH** | FINAL_ONLY sampling dead code — _parsed_fj never stored | retry_v2.py:576-585 | FINAL_ONLY mode silently produces no oracle |
| 7 | **HIGH** | subprocess_timeout hardcoded at 30s, ignores config | exec_canonical.py:129 | Config parameter has no effect |
| 8 | **MEDIUM** | parent_event_id or 0 semantic ambiguity | llm.py:123 | 0 vs None meaning unclear |
| 9 | **MEDIUM** | Silent empty-string defaults for oracle inputs | execution_v2.py:142-148 | Missing reasoning silently becomes SKIPPED |
| 10 | **MEDIUM** | No test coverage for evaluation subsystems | — | 0% coverage on 900+ lines of critical code |

### Can logs be trusted? **CONDITIONAL NO**

- Logs CAN be trusted for runs where: (a) no worker retries occurred, (b) oracle ran in baseline path (not retry), (c) no mid-run crashes
- Logs CANNOT be trusted for: (a) retry chains (oracle calls unlogged), (b) runs with worker retries (duplicate events), (c) runs that crashed before finalize()

---

## 2. END-TO-END TRACE (REAL)

### Baseline path: `execution_v2.run_v2()`

```
runner.py main() L769: load_config(args.config)
  → experiment_config.py L258-303: _parse_config(raw) → ExperimentConfig
  → including OracleConfig with inline_enabled, model, partial_mode, sampling_strategy

runner.py main() L814: run_ablation_mode(args)
  → runner.py L634: logger = RunLogger(output_dir, ...)
  → runner.py L654: logger.log_event("run.start", ...)
  → runner.py L681: run_all(cases, model, conditions, logger)
    → runner.py L270: _run_one(case, model, cond, logger)
      → runner.py L197: handle = logger.start_case(cid)
        → logging_core.py L833: trace_id = uuid4(), emit case.start event
      → runner.py L233: run_v2(case, model, condition, logger, handle.event_id)

execution_v2.py run_v2():
  L128: prompt = _render_generation_prompt(case, condition, config)
  L129: raw_response, gen_eid = _call_generation_model(prompt, ...)
    → llm.py call_model() → OpenAI/Anthropic API → logger.log_call() → event emitted
  L132: strict_parse, recovery_parse, fmt_parse = _parse_outputs(raw_response, condition)
    → NO EVENT EMITTED for parse stage
  L136: routing = _select_artifact(strict_parse, recovery_parse, case)
    → NO EVENT EMITTED for routing decision
  
  L142-148: ORACLE (raw fields, before normalize)
    raw_root_cause = fj.get("root_cause")  ← could be None
    raw_fix_strategy = fj.get("fix_strategy")  ← could be None
    → oracle_inline.py run_oracle_evaluation(raw_rc or "", raw_fs or "", ...)
      → reasoning_truth.py build_oracle_spec(), load_buggy_code(), render_prompt()
      → llm.py call_model(logger=logger) → event emitted as "oracle_eval" phase
      → reasoning_truth.py parse_response() → (label, justification, error)
    ← returns dict with status, reasoning_truth, oracle_correct, etc.
  
  L150: artifact = normalize_generation_v2(parsed_gen, case, condition)
    → NO EVENT EMITTED for normalization
  L151: recon, code = _reconstruct(parsed_gen, case, config)
    → NO EVENT EMITTED for reconstruction
  L155-156: classifier_result, classify_eid = _classify_reasoning(...)
    → evaluator_v2.py classify_case() → call_model(logger=logger) → event emitted as "classification"
  L157: ast_result = _run_ast_verification(recon, case, artifact_id)
    → ast_eval.py check_ast_patterns() → NO EVENT EMITTED, result only in payload
  L160: exec_result = _execute(case, parsed_gen, recon, config, logger)
    → exec_canonical.py → subprocess → NO SEPARATE EVENT, result in payload
  
  L162: disagreement = compute_disagreement(classifier_result, oracle_result, config)
  L163: signals = _derive_metrics(classifier_result, artifact, exec_result, parsed_gen)
  L164: evaluation = _compute_evaluation(routing, recon, exec_result, classifier_result, artifact_id)
  
  L166-169: ev = _assemble_result(..., oracle_result, disagreement)
    → Adds oracle, classification, ast_eval, evaluation, reasoning_disagreement, _schema_version
  L171: apply_validation(ev, None, -1, cid)
    → event_validation.py checks structural + semantic consistency
  L174-175: _log_result(logger, ...) 
    → logging_core.py end_case() → emits case.end event with full payload
    → logging_core.py log_run() → writes to run.jsonl (debug, NOT WAL)
```

### Events emitted per case (baseline path):
1. `case.start` (from runner.py _run_one)
2. `call.generate` (from llm.py via _call_generation_model)
3. `call.oracle_eval` (from llm.py via oracle_inline — IF logger passed)
4. `call.classify` (from llm.py via classify_case)
5. `case.end` (from logging_core.py end_case)

### MISSING events:
- **Parse stage**: no event emitted (result embedded in case.end payload)
- **Reconstruction**: no event emitted (result embedded in case.end payload)
- **AST check**: no event emitted (result embedded in case.end payload)
- **Execution subprocess**: no event emitted (result embedded in case.end payload)
- **Metric derivation**: no event emitted (result embedded in case.end payload)

These are acceptable — they're not LLM calls and their results are in the case.end payload. But it means intermediate failures between parse and case.end are only visible in the final payload, not as separate events.

---

## 3. SILENT FAILURE REPORT

### SF-1: EVENTS.JSONL APPEND MODE CAUSES DUPLICATES (CRITICAL)
**File:** `core/logging_/logging_core.py:255`
```python
self._events_file = open(self._events_path, "a", encoding="utf-8")
```
**How it fails:** Orchestrator retries a worker → same attempt_001 directory reused → events.jsonl already has events from failed first attempt → new events appended → duplicate sequence numbers → finalize() validation fails → worker marked FAILED even though case succeeded.
**Impact:** ALL baseline_v3 workers failed in the last run (164/348) due to this. Data is there but validation rejects it.

### SF-2: ORACLE LOGGER NOT PASSED IN RETRY PATH (CRITICAL)
**File:** `core/pipeline/orchestration/retry_v2.py:452`
```python
oracle_result = run_oracle_evaluation(raw_rc, raw_fs, case, config)
# Missing: logger=logger, case_id=cid, condition=condition, parent_event_id=last_parent_eid
```
**How it fails:** Oracle LLM call succeeds but is NOT recorded in events.jsonl. The `call_model()` in oracle_inline.py receives `logger=None` → `_log_call_if_logger` returns None → call is invisible.
**Impact:** Retry chains have no oracle call events in WAL. Oracle cost/latency untrackable. Event chain has gap.

### SF-3: ORACLE INPUTS SILENTLY DEFAULTED TO EMPTY STRING
**File:** `core/pipeline/orchestration/execution_v2.py:142-148`
```python
raw_root_cause = fj.get("root_cause")
if raw_root_cause is None:
    _log.warning("ORACLE INPUT: root_cause missing...")
oracle_result = run_oracle_evaluation(raw_root_cause or "", ...)
```
**How it fails:** Missing root_cause → empty string → oracle pre-filter SKIPs → oracle status = SKIPPED with `error: "pre_filter:reasoning_too_short"`. The warning is logged but the downstream status is indistinguishable from a case where reasoning was genuinely too short.
**Impact:** Analysis cannot distinguish "model produced no reasoning" from "parser failed to extract reasoning." Both show as SKIPPED.

### SF-4: AST CHECKER EXCEPTIONS AT DEBUG LEVEL
**File:** `core/evaluation/ast_eval.py:160-177`
```python
try:
    strict_ok = strict_fn(target)
except Exception as e:
    strict_ok = False
    _log.debug("strict checker failed for %s: %s", case_id, e)
```
**How it fails:** Checker throws exception → caught silently → result = False → status = measured_incorrect. At INFO log level (production), this is invisible.
**Impact:** Broken checkers produce measured_incorrect instead of crashing. Analysis treats these as legitimate structural failures.

### SF-5: FINALIZE NOT IN TRY/FINALLY
**File:** `core/pipeline/orchestration/runner.py:558-712`
```python
def run_ablation_mode(args):
    logger = RunLogger(...)  # L634
    # ... 75 lines of code that could crash ...
    stats = logger.finalize()  # L709 — never reached on crash
```
**How it fails:** Any exception between logger creation and finalize → logger never closed → no metrics.json → no calls_index.json → no validation.
**Impact:** Corrupted run appears complete but has no summary stats. Analysis tools that check for metrics.json will silently skip the run.

### SF-6: oracle.timeout PARSED BUT NEVER USED
**File:** `core/config/experiment_config.py:152` (parsed), `core/evaluation/oracle_inline.py` (not used)
```python
# Config has: oracle.timeout = 30
# But oracle_inline.py call_model() uses NO timeout parameter
cr = call_model(prompt, model=config.oracle.model, raw=True, logger=logger, ...)
# No timeout= argument
```
**How it fails:** Oracle LLM call has whatever default timeout the API client uses (120s from anthropic_client_timeout). The config value of 30s is ignored.
**Impact:** Oracle calls could hang for 120s instead of the intended 30s.

### SF-7: FINAL_ONLY SAMPLING IS DEAD CODE
**File:** `core/pipeline/orchestration/retry_v2.py:576-585`
```python
if sampling_mode == "FINAL_ONLY" and trajectory:
    best_idx = select_best_attempt(trajectory)
    best_entry = trajectory[best_idx]
    if best_entry.get("status") == "COMPLETED":
        fj_best = best_entry.get("_parsed_fj", {})  # _parsed_fj NEVER STORED
```
**How it fails:** `_parsed_fj` is never added to trajectory entries. This code block does nothing. FINAL_ONLY mode skips oracle for all attempts and never recovers.
**Impact:** If a user sets `sampling_strategy: FINAL_ONLY`, they get zero oracle evaluations.

### SF-8: SUBPROCESS TIMEOUT HARDCODED
**File:** `core/pipeline/execution/exec_canonical.py:129`
```python
_run_subprocess(timeout=30)  # Hardcoded, ignores config.execution.subprocess_timeout
```
**Impact:** Config parameter `execution.subprocess_timeout` has no effect.

### SF-9: parent_event_id OR 0 AMBIGUITY
**File:** `core/pipeline/llm.py:123`
```python
parent_event_id=parent_event_id or 0,
```
**How it fails:** `parent_event_id=0` and `parent_event_id=None` both become `0`. Falsy values conflated.

---

## 4. CONFIG SYSTEM BREAKDOWN

| param_name | source | used_in | actually_applied? | issues |
|---|---|---|---|---|
| experiment.name | YAML | runner.py print, orchestrate.py run_id | YES | — |
| experiment.seed | YAML | UNUSED | NO | Parsed but never seeds anything |
| models.generation[].name | YAML | llm.py, runner.py | YES | — |
| models.generation[].temperature | YAML | llm.py | YES | — |
| models.evaluator.name | YAML | evaluator_v2.py, oracle_inline.py | YES | — |
| models.no_temperature_prefixes | YAML | llm.py _get_model_spec | YES | Was tuple, now list (fixed) |
| oracle.inline_enabled | YAML | oracle_inline.py | YES | — |
| oracle.model | YAML | oracle_inline.py | YES | — |
| oracle.timeout | YAML | NOWHERE | **NO** | **Parsed, never used** |
| oracle.partial_mode | YAML | oracle_inline.py | YES | — |
| oracle.sampling_strategy | YAML | retry_v2.py, oracle_inline.py | PARTIAL | FINAL_ONLY is dead code |
| evaluation.classifier_mode | YAML | evaluator_v2.py, event assembly | YES | — |
| evaluation.classifier_template | YAML | evaluator_v2.py | YES | — |
| evaluation.classifier_schema_variant | YAML | evaluator_v2.py | YES | — |
| evaluation.generation_schema_variant | YAML | prompt compilation | YES | — |
| execution.subprocess_timeout | YAML | **NOWHERE** | **NO** | **Hardcoded at 30s in exec_canonical.py** |
| execution.num_workers | YAML | orchestrate.py | YES | — |
| execution.worker_timeout_seconds | YAML | orchestrate.py | YES | — |
| execution.recovery_execution | YAML | execution_v2.py routing | YES | — |
| execution.anthropic_client_timeout | YAML | llm.py client init | YES | — |
| execution.anthropic_max_output_tokens | YAML | llm.py | YES | — |
| execution.validate_prompts | YAML | prompt registry | YES | — |

---

## 5. LOGGING COVERAGE MATRIX

| Stage | Event emitted? | Event type | Key fields | Missing fields |
|---|---|---|---|---|
| Prompt build | NO | — | — | No record of which components/template used (only in prompt_assembly metadata) |
| LLM generation call | YES | call.generate | model, prompt, response, latency, call_id | — |
| Parser | NO | — | — | Parse status only in case.end payload |
| Oracle eval | **CONDITIONAL** | call.oracle_eval | model, prompt, response, latency | **Missing in retry path (logger=None)** |
| Normalization | NO | — | — | Normalization notes only in v2_artifact |
| Reconstruction | NO | — | — | Recon status only in case.end payload |
| Classifier call | YES | call.classify | model, prompt, response, latency, call_id | — |
| AST check | NO | — | — | AST result only in case.end payload.ast_eval |
| Execution subprocess | NO | — | — | Exec result only in case.end payload |
| Metric derivation | NO | — | — | Signals only in case.end payload |
| Case end (terminal) | YES | case.end | Full payload with all axes | — |

**CRITICAL GAP:** Oracle eval in retry path has `logger=None` → call event NOT emitted.

---

## 6. EVENT SCHEMA AUDIT

### Inconsistencies found:

1. **case.end payload.pass vs payload.evaluation.execution_success**: Both represent "tests passed" but derived independently. `payload.pass` comes from exec_result, `evaluation.execution_success` comes from `_compute_evaluation()`. Should always agree but no enforcement.

2. **mechanism_dim vs classifier_mechanism**: Legacy field `mechanism_dim` (from `payload.mechanism_identified_dim`) coexists with v3 field `classifier_mechanism` (from `payload.classification.mechanism_identified`). Dashboard reads both depending on schema version.

3. **_schema_version placement**: Written as `ev["_schema_version"] = "v3.1"` inside `_assemble_result()` but the field is at `payload._schema_version` in the WAL, not top-level. Dashboard schema reads it from `payload._schema_version` — this works but is non-obvious.

4. **oracle section missing in retry path events**: Because oracle calls are unlogged (SF-2), the oracle RESULT is still in the payload (from trajectory[best_idx]) but the oracle LLM CALL event is missing from the event sequence.

5. **Null handling inconsistency**: `oracle.oracle_correct` is None when UNASSESSED. `ast_eval.ast_correct` is None when not_measurable. But `classification.mechanism_identified` is None when classifier didn't run. All three use None differently — null means different things per field.

---

## 7. TEST COVERAGE GAPS

### Current test files:
- `core/tests/test_config_roundtrip.py` — 10 tests for config YAML round-trip (GOOD)
- `core/tests/test_reconstruction_logging.py` — reconstruction event tracking (LIMITED)

### ZERO tests for:

| Component | Critical function | Proposed test |
|---|---|---|
| oracle_inline | run_oracle_evaluation all paths | test_oracle_disabled, test_oracle_skipped, test_oracle_success, test_oracle_failure, test_oracle_parse_error |
| oracle_inline | Logger parameter flow | test_oracle_logger_passed_baseline, **test_oracle_logger_passed_retry** (would catch SF-2) |
| event_validation | Semantic checks | test_validation_oracle_consistency, test_validation_ast_consistency |
| event_validation | Trajectory invariants | test_validation_trajectory_complete, test_validation_trajectory_best_idx_match |
| ast_eval | Checker crash handling | test_ast_checker_exception_returns_measurable_status |
| evaluator_v2 | parse_classifier_v3_output | test_v3_parse_valid, test_v3_parse_trailing_text, test_v3_parse_wrong_keys |
| metrics_v2 | derive_v2_signals null inputs | test_signals_all_none, test_signals_partial_none |
| retry_v2 | Per-attempt axes | test_retry_trajectory_has_all_axes |
| retry_v2 | Incomplete attempt | test_retry_incomplete_attempt_entry |
| execution_v2 | Pipeline ordering | test_classifier_before_execution |
| logging_core | Append mode duplication | **test_events_not_duplicated_on_retry** (would catch SF-1) |

---

## 8. ROOT CAUSE THEMES

### Theme 1: Logging is best-effort, not contractual
- `logger=None` is accepted silently in multiple places
- No enforcement that every LLM call is logged
- Events can be silently dropped with no error

### Theme 2: Config is parsed but not enforced at use sites
- `oracle.timeout` parsed, never used
- `execution.subprocess_timeout` parsed, hardcoded override at use site
- `experiment.seed` parsed, nothing seeded

### Theme 3: File I/O assumptions break on retry
- Append mode for events.jsonl assumes single-write lifecycle
- Orchestrator retry reuses directories without clearing old data

### Theme 4: Error handling is defensive but inconsistent
- Some paths raise (assertions in logging_core)
- Some paths catch and default (AST checker exceptions)
- Some paths warn and continue (oracle missing inputs)
- No uniform policy

### Theme 5: Zero test coverage on critical evaluation paths
- Oracle, classifier, AST, metrics, validation — all untested
- The only tests are config round-trip (added today)

---

## 9. REQUIRED FIX PLAN

### P1: FIX EVENTS.JSONL APPEND DUPLICATION (CRITICAL, BLOCKING)
**File:** `core/logging_/logging_core.py:255`
**Fix:** Change to write mode (`"w"`) for fresh runs. For resume mode, the caller should pass a flag. OR: the orchestrator should clear events.jsonl before launching a retry attempt.
**Actually:** The orchestrator creates new attempt directories (attempt_002, etc.) for retries. But in the FIRST run where the config was broken (YAML tuple bug), the worker failed after writing 8 events. When the config was fixed and the orchestrator was rerun, it SAW the failed worker and re-launched on the SAME attempt_001 directory. The fix: orchestrator should truncate events.jsonl before relaunching a failed worker, or use write mode.

### P2: FIX RETRY ORACLE LOGGER (CRITICAL, BLOCKING)
**File:** `core/pipeline/orchestration/retry_v2.py:452`
**Fix:** Pass logger and related params:
```python
oracle_result = run_oracle_evaluation(
    raw_rc, raw_fs, case, config,
    logger=logger, case_id=cid, condition=condition,
    parent_event_id=last_parent_eid)
```

### P3: WRAP FINALIZE IN TRY/FINALLY (HIGH)
**File:** `core/pipeline/orchestration/runner.py`
**Fix:** Wrap the run_ablation_mode body in try/finally that calls logger.finalize().

### P4: WIRE ORACLE TIMEOUT (HIGH)
**File:** `core/evaluation/oracle_inline.py`
**Fix:** Pass `timeout=config.oracle.timeout` to call_model.

### P5: WIRE SUBPROCESS TIMEOUT FROM CONFIG (HIGH)
**File:** `core/pipeline/execution/exec_canonical.py`
**Fix:** Read `config.execution.subprocess_timeout` instead of hardcoding 30.

### P6: REMOVE FINAL_ONLY DEAD CODE OR FIX IT (HIGH)
**File:** `core/pipeline/orchestration/retry_v2.py:576-585`
**Fix:** Either store raw parsed JSON in trajectory entries for deferred oracle, or remove FINAL_ONLY as a supported strategy.

### P7: UPGRADE AST CHECKER EXCEPTION LOGGING (MEDIUM)
**File:** `core/evaluation/ast_eval.py:160-177`
**Fix:** Change `_log.debug` to `_log.warning` for checker exceptions.

### P8: FIX PARENT_EVENT_ID OR 0 (MEDIUM)
**File:** `core/pipeline/llm.py:123`
**Fix:** `parent_event_id if parent_event_id is not None else 0`

### P9: ADD TEST SUITE (HIGH, NON-BLOCKING)
Add the 11 test cases from Section 7.

### P10: ENFORCE LOGGER REQUIRED IN EXECUTION PATH (MEDIUM)
**File:** `core/evaluation/oracle_inline.py`
**Fix:** Remove `logger=None` default. Make it required. Callers that don't have a logger should explicitly pass a NullLogger, not None.
