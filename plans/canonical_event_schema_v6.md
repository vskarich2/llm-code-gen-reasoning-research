# Plan: Canonical Event Schema v6 — Final

## Context

The logging system passes `RunLogger` explicitly through the call stack. Schema knowledge leaks outside `logging_core`: `_build_metrics_payload()` in `execution.py` constructs event dicts, `log_call()` and `log_run()` each build independent record formats. This plan introduces `RunLogger.emit_event()` as the single canonical emission point.

---

## 1. Event Type Semantics — Global Definition

**Choice: Option B — backward compatibility priority.**

This is a backward compatibility concession. `aggregate.py` keys on `e["event_type"] == "case.end"`. Changing that field to a canonical value breaks all existing analysis code and all stored experiment data. The canonical type is authoritative in code (the first argument to `emit_event()`). The legacy type occupies the `event_type` key in the JSON record for backward compat.

### Field definitions (apply everywhere in this document)

| JSON field | Semantic role | Example value | Who sets it |
|---|---|---|---|
| `event_type` | Legacy event type. Used by aggregate.py and existing tooling. | `"case.end"` | `resolve_legacy_event_type()` inside `emit_event()` |
| `event_type_canonical` | Canonical event type. Authoritative classification for new consumers. | `"execution_eval"` | First argument to `emit_event()` |

There is no `event_type_legacy` field. The `event_type` field IS the legacy value. `event_type_canonical` is the canonical value. These two fields always have DIFFERENT values (they map different taxonomies). There is no scenario where they are equal.

This definition applies to every section of this document: schema, compat envelope, field mapping table, examples, and migration plan.

---

## 2. Architecture

### Single emission function

`RunLogger.emit_event(event_type_canonical, *, ...keyword_args) -> int` is the ONLY function that writes to events.jsonl. The first positional argument is named `event_type_canonical` in the function signature to eliminate ambiguity. All other methods are thin wrappers.

`emit_event()` performs these steps in order:

1. Validate `event_type_canonical` ∈ `{"llm_call", "execution_eval", "reasoning_eval", "pipeline_state", "error"}`
2. Enforce `PARENT_REQUIRED` constraint
3. If `raw_ev` is provided: call `_build_canonical_and_extra(raw_ev, runtime_ms)` → receive `(execution_section, reasoning_section, extra_section, consumed_keys)`
4. Run overlap invariant check
5. Assemble the full record: insert returned sections directly — `emit_event()` does NOT read `raw_ev` for any field belonging to `execution`, `reasoning`, or `extra`
6. Compute `event_type` via `resolve_legacy_event_type(event_type_canonical, phase, step)`
7. Build compat envelope (flat legacy keys)
8. Assign `event_id`, `timestamp`, `event_index_within_trace`
9. Write to events.jsonl
10. Return `event_id`

### Canonical schema (as written to events.jsonl)

```json
{
  "schema_version": "1.0",
  "event_id": "int",
  "event_type": "case.end | call.generate | case.failed | ...",
  "event_type_canonical": "llm_call | execution_eval | reasoning_eval | pipeline_state | error",
  "timestamp": "ISO-8601",
  "run":       { "run_id", "experiment_name", "trial", "model" },
  "trace":     { "trace_id", "parent_event_id", "trajectory_id", "event_index_within_trace" },
  "context":   { "case_id", "condition", "attempt_idx", "step", "phase", "node", "edge" },
  "prompt":    { "prompt_family", "prompt_name", "prompt_version", "prompt_hash", "template_id", "variables_hash", "tokens_input_estimate" },
  "llm_call":  { "call_id", "provider", "model", "temperature", "max_tokens", "tokens_output_estimate", "latency_ms", "status", "error_type", "request_path", "response_path", "flat_path" },
  "execution": { "ran", "passed", "score", "tests_run", "tests_passed", "runtime_ms", "error" },
  "reasoning": { "evaluated", "reasoning_correct", "failure_type", "confidence" },
  "artifacts": { "code_path", "diff_path", "stdout_path", "stderr_path" },
  "metrics":   { "cumulative_calls", "cumulative_cost" },
  "extra":     {}
}
```

Plus flat legacy keys at top level for aggregate.py: `model`, `condition`, `case_id`, `trace_id`, `trial`, `phase`, `payload`.

All 14 canonical sections are ALWAYS present. Inapplicable fields are `null`.

---

## 3. Schema Definition Boundaries

Field membership and schema structure are orthogonal responsibilities. They are defined in separate functions that do not duplicate each other's concerns.

### Field membership

Defined by `_build_canonical_and_extra()`. This function determines:
- Which `raw_ev` fields belong to the `execution` section
- Which `raw_ev` fields belong to the `reasoning` section
- Which `raw_ev` fields go to `extra` (everything not consumed)

No other function makes field membership decisions. Adding a canonical field means modifying `_build_canonical_and_extra()` in one location.

### Schema structure

Defined by `emit_event()`. This function determines:
- The 14-section layout of the event record
- Where extracted sections are placed in the record
- Which sections are populated from keyword args vs internal state vs extraction output
- The compat envelope (flat legacy keys, `payload` dict)

`emit_event()` does not decide which `raw_ev` fields are canonical — it delegates that to `_build_canonical_and_extra()` and inserts the returned dicts by reference.

### Non-duplication claim (precise)

No duplication exists in field membership definition. `_build_canonical_and_extra()` is the sole authority for which `raw_ev` fields map to which canonical section. Schema structure (the event record layout) is defined separately in `emit_event()` and is intentionally a distinct responsibility.

---

## 4. Extraction — Single Source of Truth for Field Membership

```python
def _build_canonical_and_extra(
    self, raw_ev: dict, runtime_ms: float | None
) -> tuple[dict, dict, dict, set]:
    """Extract canonical sections from raw_ev.

    Returns (execution_section, reasoning_section, extra_section, consumed_keys).

    Field membership is defined SOLELY by what this function reads.
    consumed_keys tracks every key read. extra = raw_ev minus consumed_keys.
    """
    consumed_keys: set[str] = set()

    # --- execution section ---
    exec_data = raw_ev.get("execution", {})
    consumed_keys.add("execution")
    execution_section = {
        "ran": exec_data.get("ran"),
        "passed": raw_ev.get("pass"),
        "score": raw_ev.get("score"),
        "tests_run": exec_data.get("total_tests"),
        "tests_passed": exec_data.get("tests_passed"),
        "runtime_ms": runtime_ms,
        "error": exec_data.get("error"),
    }
    consumed_keys.update({"pass", "score"})

    # --- reasoning section ---
    reasoning_section = {
        "evaluated": raw_ev.get("reasoning_correct") is not None,
        "reasoning_correct": raw_ev.get("reasoning_correct"),
        "failure_type": raw_ev.get("failure_type"),
        "confidence": raw_ev.get("confidence"),
    }
    consumed_keys.update({"reasoning_correct", "failure_type", "confidence"})

    # --- keys consumed for context (used by emit_event for context section, not stored in execution/reasoning) ---
    consumed_keys.update({"condition", "operator_used", "num_attempts", "alignment"})

    # --- extra: everything NOT consumed ---
    extra_section = {k: v for k, v in raw_ev.items() if k not in consumed_keys}

    return execution_section, reasoning_section, extra_section, consumed_keys
```

### How emit_event() uses the output

```python
if raw_ev is not None:
    exec_sec, reas_sec, extra_sec, consumed = self._build_canonical_and_extra(raw_ev, runtime_ms)
    self._enforce_no_overlap(consumed, extra_sec)
    record["execution"] = exec_sec
    record["reasoning"] = reas_sec
    record["extra"] = extra_sec
else:
    record["execution"] = _null_execution()
    record["reasoning"] = _null_reasoning()
    record["extra"] = extra or {}
```

`emit_event()` inserts returned dicts by reference. It does not read `raw_ev`.

---

## 5. Runtime Invariant: No Overlap Between Canonical and Extra

```python
def _enforce_no_overlap(self, consumed_keys: set, extra_section: dict):
    overlap = consumed_keys & set(extra_section.keys())
    if overlap:
        raise RuntimeError(
            f"SCHEMA INVARIANT VIOLATION: keys {overlap} appear in both "
            f"canonical sections and extra. Fix _build_canonical_and_extra()."
        )
```

Runs inside `emit_event()` after extraction, before any write. Every event with `raw_ev` is checked.

---

## 6. Formal Trajectory Definition

A **trajectory** is a maximal sequence of causally linked events within a trace where each event's existence is unconditionally determined by the preceding event.

A new `trajectory_id` is created at the start of any execution segment whose existence depends on the outcome of a prior event within the same trace.

| Transition | Same trajectory? | Reason |
|---|---|---|
| generation → its evaluation | YES | Evaluation exists unconditionally. |
| generation → classification of that generation | YES | Classification exists unconditionally. |
| evaluation (fail) → retry generation | NO | Retry exists only because eval failed. |
| gate check (fail) → retry generation | NO | Retry exists only because gate failed. |
| contract parse (fail) → fallback evaluation | NO | Fallback exists only because parse failed. |
| DAG node A → node B (unconditional edge) | YES | B exists regardless of A's outcome. |
| DAG node A → node B (conditional edge) | NO | B depends on A's outcome. |

### When `new_trajectory()` is called per execution path

| Path | Boundary | When |
|---|---|---|
| `run_single` | None | Never |
| `run_repair_loop` | eval(fail) → attempt 2 | Before second `call_model` |
| `run_contract_gated` | gate(fail) → retry | Before retry `call_model` |
| `run_contract_gated` | parse(fail) → fallback | Before `_fallback_run()` |
| `run_leg_reduction` | None | Never |
| `run_v2` | None | Never |
| `run_retry_harness` | eval(fail) → k+1 | Before `call_model` at each k > 0 |

---

## 7. Parent Event ID — Strict Enforcement

```python
PARENT_REQUIRED = frozenset({"llm_call", "execution_eval", "reasoning_eval", "error"})
```

For these canonical event types, `parent_event_id is None` raises `RuntimeError` before any write. `pipeline_state`: `parent_event_id` is `null`, not enforced.

### Parent source table

| Path | Event (canonical type) | parent_event_id |
|---|---|---|
| `run_single` | `llm_call` (gen) | `case_start_eid` |
| `run_single` | `execution_eval` | `gen_eid` |
| `run_repair_loop` | `llm_call` (attempt 1) | `case_start_eid` |
| `run_repair_loop` | `execution_eval` (pass, early) | `gen1_eid` |
| `run_repair_loop` | `llm_call` (attempt 2) | `gen1_eid` |
| `run_repair_loop` | `execution_eval` (final) | `gen2_eid` |
| `run_contract_gated` | `llm_call` (elicit) | `case_start_eid` |
| `run_contract_gated` | `llm_call` (code gen) | `elicit_eid` |
| `run_contract_gated` | `llm_call` (retry) | `code_gen_eid` |
| `run_contract_gated` | `execution_eval` | last `llm_call` eid |
| `_fallback_run` | `execution_eval` | `elicit_eid` |
| `run_leg_reduction` | `llm_call` (gen) | `case_start_eid` |
| `run_leg_reduction` | `execution_eval` | `gen_eid` |
| `run_v2` | `llm_call` (gen) | `case_start_eid` |
| `run_v2` | `llm_call` (classify) | `gen_eid` |
| `run_v2` | `execution_eval` | `classify_eid` or `gen_eid` if classifier skipped |
| `run_retry_harness` | `llm_call` (k=0) | `case_start_eid` |
| `run_retry_harness` | `llm_call` (k>0) | previous iteration's last eid |
| `run_retry_harness` | `execution_eval` (final) | last `llm_call` eid |
| any path | `error` (exception) | `case_start_eid` |

---

## 8. Prompt Identity — Computed by Caller

logging_core stores prompt fields verbatim. It computes none of them.

### `variables_hash`

Hashes the full serialized variable mapping (keys AND values):

```python
variables_canonical = json.dumps(variables, sort_keys=True, default=str)
variables_hash = hashlib.sha256(variables_canonical.encode()).hexdigest()
```

### `_capture_prompt_assembly()` (in execution.py)

```python
def _capture_prompt_assembly(rendered, variables: dict, condition: str, full_prompt: str) -> dict:
    import hashlib, json
    try:
        from experiment_config import get_config
        config_name = get_config().experiment.name
    except Exception:
        config_name = None
    return {
        "prompt_family": condition,
        "prompt_name": rendered.plan_hash,
        "prompt_version": config_name,
        "prompt_hash": hashlib.sha256(full_prompt.encode()).hexdigest(),
        "template_id": rendered.final_prompt_hash,
        "variables_hash": hashlib.sha256(
            json.dumps(variables, sort_keys=True, default=str).encode()
        ).hexdigest(),
    }
```

---

## 9. Token Estimate Semantics

`tokens_input_estimate` and `tokens_output_estimate` are integer estimates. They are not exact token counts.

Both use `_estimate_prompt_tokens(text: str, model: str) -> int` in execution.py:
- When `tiktoken` is installed: exact BPE token count for the model's tokenizer (falls back to `cl100k_base` if model unknown).
- When `tiktoken` is not installed: `len(text) // 4`.

Same function for input and output: both are strings tokenized by the same model's tokenizer. Separate functions would be identical duplication.

Callers compute estimates and pass them. logging_core stores values verbatim.

---

## 10. Compatibility Envelope

### `resolve_legacy_event_type(event_type_canonical, phase, step) -> str`

```python
def resolve_legacy_event_type(event_type_canonical: str, phase: str | None, step: str | None) -> str:
    if event_type_canonical == "llm_call":
        if phase == "classification":
            return "call.classify"
        if phase == "generation":
            return "call.generate"
        return "call.other"
    if event_type_canonical == "execution_eval":
        return "case.end"
    if event_type_canonical == "reasoning_eval":
        return "case.end"
    if event_type_canonical == "error":
        return "case.failed"
    if event_type_canonical == "pipeline_state":
        if step == "case_start":
            return "case.start"
        if step == "run_start":
            return "run.start"
        if step == "run_end":
            return "run.end"
        if step == "run_failed":
            return "run.failed"
        if step == "metric":
            return "metric.record"
        if step == "parse":
            return "parse.result"
        return "pipeline_state"
    return event_type_canonical
```

Returns a string for every input. Never returns null.

### Written record layout

```json
{
  "event_type": "case.end",
  "event_type_canonical": "execution_eval",
  "model": "gpt-4.1-nano",
  "condition": "baseline_v2",
  "case_id": "alias_config_a",
  "trace_id": "57f4fc04...",
  "trial": 1,
  "phase": "case",
  "event_id": 5,
  "payload": {"pass": true, "score": 1.0, "failure_type": null, ...},
  "schema_version": "1.0",
  "run": {"run_id": "...", "experiment_name": "...", "trial": 1, "model": "gpt-4.1-nano"},
  "trace": {"trace_id": "57f4fc04...", "parent_event_id": 3, "trajectory_id": "a1b2c3...", "event_index_within_trace": 3},
  "context": {"case_id": "alias_config_a", "condition": "baseline_v2", ...},
  "prompt": {...},
  "llm_call": {...},
  "execution": {"ran": true, "passed": true, "score": 1.0, ...},
  "reasoning": {"evaluated": false, "reasoning_correct": null, ...},
  "artifacts": {...},
  "metrics": {...},
  "extra": {...}
}
```

### `_build_compat_payload(record) -> dict`

- `llm_call` → `{"call_id": ..., "latency_ms": ..., "prompt_length": ..., "response_length": ..., "error": ...}`
- `execution_eval` → `{"pass": ..., "score": ..., "failure_type": ..., **extra}`
- `error` → `{"error": ...}`
- `pipeline_state` → `{}`

---

## 11. run.jsonl Contract

### Allowed fields (exhaustive)

`canonical_event_id`, `run_id`, `trace_id`, `case_id`, `condition`, `timestamp`, `prompt_length`, `raw_response_length`, `parsed_reasoning` (2000 char max), `parsed_code_length`, `parse_error`, `response_format`, `data_lineage`.

### Forbidden

Any field from canonical `execution`, `reasoning`, `prompt`, `llm_call`, `metrics`, or `artifacts` sections. Specifically: `pass`, `score`, `ran`, `tests_run`, `tests_passed`, `reasoning_correct`, `failure_type`, `confidence`, `latency_ms`, `call_id`, `prompt_hash`, `tokens_input_estimate`, `temperature`, `max_tokens`.

### `log_run()` signature

```python
def log_run(self, case_id: str, condition: str, prompt: str,
            raw_output: str, parsed: dict, canonical_event_id: int) -> None:
```

Does not accept `ev`. Writes only allowed fields.

---

## 12. Field Mapping Table

(A) = caller, (B) = RunLogger internal, (C) = constant/config

| Field | Class | Source |
|---|---|---|
| `schema_version` | (C) | `"1.0"` |
| `event_id` | (B) | `self._event_counter` |
| `event_type` | (B) | `resolve_legacy_event_type()` output — legacy value |
| `event_type_canonical` | (A) | First arg to `emit_event()` — canonical value |
| `timestamp` | (B) | `datetime.now().isoformat()` |
| `run.run_id` | (B) | `self._run_id` |
| `run.experiment_name` | (B) | `self._experiment_name` |
| `run.trial` | (B) | `self._trial` |
| `run.model` | (B) | `self._model` |
| `trace.trace_id` | (B) | `self._current_trace_id` |
| `trace.parent_event_id` | (A) | Caller (REQUIRED for llm_call/execution_eval/reasoning_eval/error) |
| `trace.trajectory_id` | (B) | `self._current_trajectory_id` |
| `trace.event_index_within_trace` | (B) | `self._trace_event_counter` |
| `context.case_id` | (A) | Caller |
| `context.condition` | (A/B) | Caller or `self._condition` |
| `context.attempt_idx` | (A) | Caller |
| `context.step` | (A) | Caller |
| `context.phase` | (A) | Caller |
| `context.node` | (A) | Caller (null for non-graph) |
| `context.edge` | (A) | Caller (null for non-graph) |
| `prompt.*` | (A) | All 7 fields from caller's `prompt_assembly` dict |
| `llm_call.call_id` | (B) | `self._call_counter` |
| `llm_call.provider` | (C) | `"openai"` |
| `llm_call.model` | (A) | Caller |
| `llm_call.temperature` | (C) | experiment_config |
| `llm_call.max_tokens` | (C) | experiment_config |
| `llm_call.tokens_output_estimate` | (A) | Caller |
| `llm_call.latency_ms` | (A) | Caller |
| `llm_call.status` | (A) | Caller |
| `llm_call.error_type` | (A) | Caller |
| `llm_call.request_path` | (B) | Computed from call_id |
| `llm_call.response_path` | (B) | Computed from call_id |
| `llm_call.flat_path` | (B) | Computed from call_id + phase |
| `execution.*` | (B) | Returned by `_build_canonical_and_extra()` |
| `reasoning.*` | (B) | Returned by `_build_canonical_and_extra()` |
| `artifacts.*` | (A) | Caller (all null currently) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (null currently) |
| `extra` | (B) | Returned by `_build_canonical_and_extra()` |

---

## 13. Call Site Contracts

execution.py, execution_v2.py, runner.py, llm.py, retry_harness.py MUST NOT construct event dictionaries.

### runner.py
- `RunLogger(run_dir, run_id, model, condition=None, trial, experiment_name=...)`
- `handle = logger.start_case(cid)` → `CaseHandle(trace_id, event_id)`
- Passes `handle.event_id` as `case_start_eid` to execution functions
- `logger.fail_case(cid, error_str, condition=condition, parent_event_id=handle.event_id)`

### execution.py
- `gen_eid = logger.log_call(...)` — captures event_id
- `end_eid = logger.end_case(cid, condition=condition, raw_ev=ev, runtime_ms=..., parent_event_id=gen_eid)`
- `logger.log_run(cid, condition, prompt, raw_output, parsed, canonical_event_id=end_eid)`
- Does NOT call `_build_metrics_payload()` — deleted
- Does NOT select extra fields — automatic via `_build_canonical_and_extra()`

### llm.py
- `_log_call_if_logger()` passes raw args + `parent_event_id` to `logger.log_call()`

---

## 14. Migration Plan

### Step 1: `emit_event()` + extraction + invariants in logging_core.py
- Add `emit_event(event_type_canonical, *, ...)` per Section 2
- Add `_build_canonical_and_extra()` per Section 4
- Add `_enforce_no_overlap()` per Section 5
- Add `resolve_legacy_event_type()` per Section 10
- Add `_build_compat_payload()`, `_build_compat_envelope()`
- Add `PARENT_REQUIRED` enforcement
- Add `experiment_name` to constructor
- Add `_current_trajectory_id`, `_trace_event_counter`, `new_trajectory()`
- `start_case()` returns `CaseHandle(trace_id, event_id)`
- Test: canonical + compat output, parent enforcement, overlap invariant

### Step 2: Convert `log_call()` → `emit_event("llm_call", ...)`
- File writes unchanged. Event write delegates to `emit_event()`
- `log_call()` requires `parent_event_id`
- Test: events.jsonl `event_type` field is legacy string, `event_type_canonical` is `"llm_call"`

### Step 3: Convert case lifecycle → `emit_event()`
- `end_case(case_id, *, condition, raw_ev, runtime_ms, parent_event_id)`
- `fail_case(case_id, error, *, condition, parent_event_id)`
- Test: `event_type` = `"case.end"`, `event_type_canonical` = `"execution_eval"`

### Step 4: Convert `log_event()` / `log_metric()` → `emit_event("pipeline_state", ...)`
- Test: `event_type` = `"run.start"`, `event_type_canonical` = `"pipeline_state"`

### Step 5: Update `_capture_prompt_assembly()` in execution.py
- Add `full_prompt` param
- Compute `prompt_hash` (sha256 of full prompt)
- Compute `variables_hash` (sha256 of canonical JSON of full variable mapping)
- Test: hashes correct, differ for same keys with different values

### Step 6: Update runner.py
- Pass `experiment_name`, capture `CaseHandle`, thread `parent_event_id`
- Test: e2e smoke

### Step 7: Update execution.py
- Pass `raw_ev` to `end_case()`, capture event_ids for parent chaining
- Call `new_trajectory()` before retry in `run_repair_loop`
- Call `new_trajectory()` before retry in `run_contract_gated`
- Call `new_trajectory()` before `_fallback_run()`
- Delete `_build_metrics_payload()`
- Test: all v1 conditions

### Step 8: Update execution_v2.py
- Chain: `gen_eid → classify_eid → end_eid`
- Test: v2 conditions

### Step 9: Update retry_harness.py
- `new_trajectory()` before each k > 0
- Chain parent_event_id through loop
- Test: retry with correct trajectory + parent chain

### Step 10: Update `log_run()` contract
- New signature with `canonical_event_id`. Only debug fields.
- Test: run.jsonl has no forbidden fields

### Step 11: Update `finalize()` / `validate()`
- Validate: all 14 sections present, parent enforcement, case pairing
- Test: metrics.json correct

---

## 15. Verification

1. `emit_event()` canonical + compat output for all 5 canonical event types
2. Smoke test: 3 cases × 3 conditions, aggregate.py produces identical dashboard.json
3. `finalize()` validates every event structurally
4. Parent chain: CGE elicit→code→retry→eval forms correct DAG
5. Parent enforcement: missing parent on `llm_call` raises RuntimeError
6. Overlap invariant: field in both canonical and extra raises RuntimeError
7. Inverse mapping: new field added to `ev` automatically appears in `extra`
8. run.jsonl: zero forbidden canonical fields
9. Trajectory: `run_repair_loop` creates 2; `run_contract_gated` with retry creates 2; with fallback creates 2; `run_retry_harness` creates N
10. `resolve_legacy_event_type()` correct for all canonical type × phase × step
11. `variables_hash` differs for same keys with different values
12. `event_type` field in JSON is legacy; `event_type_canonical` is canonical — verified in all test events
13. No `_CANONICAL_RAW_EV_FIELDS` or equivalent static set exists (grep verification)

---

## 16. Global Consistency Verification

The following consistency properties hold across all sections of this document:

1. `event_type` means legacy value everywhere: schema definition (Section 2), compat envelope (Section 10), field mapping table (Section 12), migration tests (Section 14), examples (Section 10).
2. `event_type_canonical` means canonical value everywhere: schema definition (Section 2), `emit_event()` first argument (Section 2), field mapping table (Section 12), migration tests (Section 14).
3. Field membership is defined solely by `_build_canonical_and_extra()` (Section 4). No other section defines or enumerates canonical `raw_ev` fields.
4. Schema structure is defined solely by `emit_event()` (Section 2). It inserts extraction output by reference (Section 4).
5. The overlap invariant (Section 5) prevents field membership drift at runtime.
6. The field mapping table (Section 12) classifies `execution.*`, `reasoning.*`, and `extra` as (B) "returned by `_build_canonical_and_extra()`" — consistent with Section 3's boundary definition.

---

## Files Modified

| Step | File |
|------|------|
| 1–4, 10–11 | `logging_core.py` |
| 5, 7 | `execution.py` |
| 6 | `runner.py` |
| 8 | `execution_v2.py` |
| 9 | `retry_harness.py` |
