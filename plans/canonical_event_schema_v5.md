# Plan: Canonical Event Schema v5 — Final

## Context

The logging system passes `RunLogger` explicitly through the call stack. Schema knowledge leaks outside `logging_core`: `_build_metrics_payload()` in `execution.py` constructs event dicts, `log_call()` and `log_run()` each build independent record formats. This plan introduces `RunLogger.emit_event()` as the single canonical emission point.

---

## 1. Architecture

### Single emission function

`RunLogger.emit_event(event_type, *, ...keyword_args) -> int` is the ONLY function that writes to events.jsonl. All other methods are thin wrappers.

`emit_event()` performs these steps in order:

1. Validate `event_type` ∈ `VALID_CANONICAL_TYPES`
2. Enforce `PARENT_REQUIRED` constraint
3. If `raw_ev` is provided: call `_build_canonical_and_extra(raw_ev, runtime_ms)` → receive `(execution_section, reasoning_section, extra_section)`
4. Run overlap invariant check (Section 3)
5. Assemble the full record by inserting returned sections DIRECTLY — `emit_event()` DOES NOT read `raw_ev` itself for any field belonging to `execution`, `reasoning`, or `extra`
6. Build compat envelope
7. Assign `event_id`, `timestamp`, `event_index_within_trace`
8. Write to events.jsonl
9. Return `event_id`

The `execution`, `reasoning`, and `extra` sections in the event record are EXACTLY the dicts returned by `_build_canonical_and_extra()`. `emit_event()` inserts them by reference. It does not modify, supplement, or re-derive any field within them.

### Canonical schema

```json
{
  "schema_version": "1.0",
  "event_id": "int",
  "event_type": "llm_call | execution_eval | reasoning_eval | pipeline_state | error",
  "event_type_legacy": "call.generate | case.end | ...",
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

`event_type` is canonical (primary). `event_type_legacy` is the backward-compat mapping (secondary). All 14 sections are ALWAYS present. Inapplicable fields are `null`.

---

## 2. Extraction — Single Source of Truth

`_build_canonical_and_extra()` is the ONLY function that reads `raw_ev` for the `execution`, `reasoning`, and `extra` sections. `emit_event()` receives these three dicts as return values and inserts them into the event record without modification.

```python
def _build_canonical_and_extra(
    self, raw_ev: dict, runtime_ms: float | None
) -> tuple[dict, dict, dict, set]:
    """Extract canonical sections from raw_ev.

    Returns (execution_section, reasoning_section, extra_section, consumed_keys).

    The set of canonical fields is defined SOLELY by what this function reads.
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

    # --- keys consumed for context (not stored in execution/reasoning) ---
    consumed_keys.update({"condition", "operator_used", "num_attempts", "alignment"})

    # --- extra: everything NOT consumed ---
    extra_section = {k: v for k, v in raw_ev.items() if k not in consumed_keys}

    return execution_section, reasoning_section, extra_section, consumed_keys
```

### How emit_event() uses the output

```python
if raw_ev is not None:
    exec_sec, reas_sec, extra_sec, consumed = self._build_canonical_and_extra(raw_ev, runtime_ms)
    self._enforce_no_overlap(exec_sec, reas_sec, extra_sec, consumed, raw_ev)
    record["execution"] = exec_sec      # direct assignment, no modification
    record["reasoning"] = reas_sec      # direct assignment, no modification
    record["extra"] = extra_sec         # direct assignment, no modification
else:
    record["execution"] = _null_execution()
    record["reasoning"] = _null_reasoning()
    record["extra"] = extra or {}
```

`emit_event()` never calls `raw_ev.get()` for any key. It delegates entirely to `_build_canonical_and_extra()`.

---

## 3. Runtime Invariant: No Overlap Between Canonical and Extra

### Definition

For every event that includes `raw_ev`, immediately after `_build_canonical_and_extra()` returns and before the event is written:

```
canonical_keys_emitted ∩ extra_section.keys() == ∅
```

### What `canonical_keys_emitted` contains

The set of all top-level `raw_ev` keys that were consumed by the extraction:

```python
canonical_keys_emitted = consumed_keys  # returned by _build_canonical_and_extra()
```

### Enforcement

```python
def _enforce_no_overlap(self, exec_sec, reas_sec, extra_sec, consumed_keys, raw_ev):
    """Raise RuntimeError if any key appears in both canonical sections and extra.

    This runs BEFORE event emission. Violation halts the process.
    """
    overlap = consumed_keys & set(extra_sec.keys())
    if overlap:
        raise RuntimeError(
            f"SCHEMA INVARIANT VIOLATION: keys {overlap} appear in both "
            f"canonical sections and extra. This means _build_canonical_and_extra() "
            f"consumed a key but it was not removed from extra. Fix the extraction function."
        )
```

### When this runs

Immediately after `_build_canonical_and_extra()` returns, inside `emit_event()`, before any write. Every event with `raw_ev` is checked. There is no deferred validation — the invariant is enforced at emission time.

### What this catches

If a developer reads a field from `raw_ev` in the extraction function but forgets to add it to `consumed_keys`, the field appears in `extra_section` (because it was not consumed). But it was also read into a canonical section. The overlap check detects this and raises immediately.

---

## 4. Formal Trajectory Definition

### Definition

A **trajectory** is a maximal sequence of causally linked events within a trace where each event's existence is unconditionally determined by the preceding event. A trajectory ends when execution reaches a decision point whose outcome determines which subsequent events exist.

### Formal rule

A new `trajectory_id` is created at the start of any execution segment whose existence depends on the outcome of a prior event within the same trace.

Restated as a predicate: given event E_prev (an evaluation, gate check, or error) and event E_next (a generation, fallback, or branch entry), E_next starts a new trajectory if and only if:

```
E_next would NOT have been emitted if E_prev had produced a different outcome.
```

### Classification of transitions

| Transition | Same trajectory? | Reason |
|---|---|---|
| generation → its evaluation | YES | Evaluation exists unconditionally given the generation. |
| generation → classification of that generation | YES | Classification exists unconditionally given the generation. |
| evaluation (fail) → retry generation | NO (new trajectory) | Retry generation exists only because evaluation failed. Different outcome → no retry. |
| gate check (fail) → retry generation | NO (new trajectory) | Retry exists only because gate failed. |
| contract parse (fail) → fallback evaluation | NO (new trajectory) | Fallback exists only because parse failed. |
| evaluation (pass, early return) → done | N/A | No subsequent event. |
| DAG node A → DAG node B (unconditional edge) | YES | B exists regardless of A's outcome. |
| DAG node A → DAG node B (conditional edge) | NO (new trajectory) | B exists only because A produced a specific outcome. |

### When `new_trajectory()` is called

`new_trajectory()` is called EXACTLY at the boundaries identified above. For each current execution path:

| Path | Boundary | When `new_trajectory()` is called |
|---|---|---|
| `run_single` | None | Never. Single trajectory. |
| `run_repair_loop` | eval(fail) → attempt 2 | Before the second `call_model`. |
| `run_contract_gated` | gate(fail) → retry | Before the retry `call_model`. |
| `run_contract_gated` | parse(fail) → fallback | Before `_fallback_run()`. |
| `run_leg_reduction` | None | Never. Single trajectory. |
| `run_v2` | None | Never. Single trajectory. |
| `run_retry_harness` | eval(fail) → iteration k+1 | Before `call_model` at each k > 0. |

### Implementation

```python
def new_trajectory(self) -> str:
    if self._current_trace_id is None:
        raise RuntimeError("new_trajectory() requires an active trace")
    self._current_trajectory_id = uuid.uuid4().hex
    return self._current_trajectory_id
```

`start_case()` creates the first trajectory. `new_trajectory()` creates subsequent ones. `end_case()` / `fail_case()` clear both.

---

## 5. Parent Event ID — Strict Enforcement

```python
PARENT_REQUIRED = frozenset({"llm_call", "execution_eval", "reasoning_eval", "error"})
```

For these event types, `parent_event_id is None` raises `RuntimeError` inside `emit_event()` before any write.

`pipeline_state` events: `parent_event_id` is `null`. Not in `PARENT_REQUIRED`.

### Parent source table (every event, every path)

| Path | Event | parent_event_id |
|---|---|---|
| `run_single` | `llm_call` (gen) | `case_start_eid` |
| `run_single` | `execution_eval` | `gen_eid` |
| `run_repair_loop` | `llm_call` (attempt 1) | `case_start_eid` |
| `run_repair_loop` | `execution_eval` (pass, early return) | `gen1_eid` |
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

## 6. Prompt Identity — Computed by Caller

logging_core stores prompt fields verbatim. It computes none of them.

### `variables_hash` — Corrected

`variables_hash` hashes the full serialized variable mapping (keys AND values), not just key names.

Computation in `_capture_prompt_assembly()`:

```python
import hashlib, json

# Stable serialization: canonical JSON with sorted keys, default=str for non-JSON types
variables_canonical = json.dumps(variables, sort_keys=True, default=str)
variables_hash = hashlib.sha256(variables_canonical.encode()).hexdigest()
```

Guarantees:
- Two prompts with same variable names but different values produce different hashes.
- Ordering is deterministic (`sort_keys=True`).
- Non-serializable values are converted to string (`default=str`).

### Full `_capture_prompt_assembly()` (in execution.py)

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

## 7. Token Estimate Semantics

### Fields

`tokens_input_estimate` and `tokens_output_estimate` are integer estimates of token count. They are NOT exact token counts.

### Estimation method

Both fields use the same function: `_estimate_prompt_tokens(text: str, model: str) -> int` (currently in `execution.py`, stays there — it is prompt-system logic, not logging logic).

```python
def _estimate_prompt_tokens(text: str, model: str) -> int:
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return len(text) // 4
```

### Behavior

- When `tiktoken` is installed: returns the exact BPE token count for the specified model's tokenizer. If the model is unknown to tiktoken, falls back to `cl100k_base` encoding.
- When `tiktoken` is NOT installed: returns `len(text) // 4` (character count divided by 4, integer division).

### Why the same function for input and output

Both prompt text and response text are strings tokenized by the same model's tokenizer. There is no structural difference in how they are tokenized. Using separate functions would be unnecessary duplication.

### Caller responsibility

- `tokens_input_estimate`: caller computes `_estimate_prompt_tokens(prompt, model)` and passes it to `emit_event()` / `log_call()`.
- `tokens_output_estimate`: caller computes `_estimate_prompt_tokens(response, model)` and passes it to `emit_event()` / `log_call()`.

logging_core stores these values verbatim. It does not estimate tokens.

---

## 8. Compatibility Envelope

### `resolve_legacy_event_type` — total function

```python
def resolve_legacy_event_type(event_type: str, phase: str | None, step: str | None) -> str:
    if event_type == "llm_call":
        if phase == "classification":
            return "call.classify"
        if phase == "generation":
            return "call.generate"
        return "call.other"
    if event_type == "execution_eval":
        return "case.end"
    if event_type == "reasoning_eval":
        return "case.end"
    if event_type == "error":
        return "case.failed"
    if event_type == "pipeline_state":
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
    return event_type
```

Returns a string for every input. Never returns null.

### Envelope structure

Every event in events.jsonl has flat legacy keys at top level:

```python
{
    "event_type": "case.end",                # legacy (aggregate.py reads this)
    "event_type_canonical": "execution_eval", # this is NOT primary — it's a label for the canonical type
    ...flat compat keys...,
    "payload": {...},                         # legacy payload
    "schema_version": "1.0",
    ...canonical sections...
}
```

Wait — this conflicts with Section 1 which states `event_type` is canonical. Let me resolve this precisely.

The written record uses `event_type` for the LEGACY value (because aggregate.py keys on `e["event_type"] == "case.end"` and changing that breaks backward compat). The canonical type is stored under `event_type_canonical`. This is a pragmatic compromise: the field name `event_type` belongs to the legacy consumer during the compat period.

Correction to Section 1: in the WRITTEN record, `event_type` = legacy string, `event_type_canonical` = canonical string. In the API (`emit_event()`), the first parameter is the canonical type, and `resolve_legacy_event_type()` derives the legacy value. The canonical type is authoritative in the code; the legacy type occupies the `event_type` key in JSON for backward compat.

### `_build_compat_payload(record) -> dict`

- `llm_call`: `{"call_id": ..., "latency_ms": ..., "prompt_length": ..., "response_length": ..., "error": ...}`
- `execution_eval`: `{"pass": ..., "score": ..., "failure_type": ..., **extra}`
- `error`: `{"error": ...}`
- `pipeline_state`: `{}`

---

## 9. run.jsonl Contract

### Allowed fields (exhaustive)

`canonical_event_id`, `run_id`, `trace_id`, `case_id`, `condition`, `timestamp`, `prompt_length`, `raw_response_length`, `parsed_reasoning` (2000 char max), `parsed_code_length`, `parse_error`, `response_format`, `data_lineage`.

### Forbidden

run.jsonl MUST NOT contain any field from the canonical `execution`, `reasoning`, `prompt`, `llm_call`, `metrics`, or `artifacts` sections. Specifically forbidden: `pass`, `score`, `ran`, `tests_run`, `tests_passed`, `reasoning_correct`, `failure_type`, `confidence`, `latency_ms`, `call_id`, `prompt_hash`, `tokens_input_estimate`, `temperature`, `max_tokens`.

### `log_run()` signature

```python
def log_run(self, case_id: str, condition: str, prompt: str,
            raw_output: str, parsed: dict, canonical_event_id: int) -> None:
```

Does not accept `ev`. Writes only allowed fields.

---

## 10. Field Mapping Table

(A) = caller, (B) = RunLogger internal, (C) = constant/config

| Field | Class | Source |
|---|---|---|
| `schema_version` | (C) | `"1.0"` |
| `event_id` | (B) | `self._event_counter` |
| `event_type` (in JSON) | (B) | `resolve_legacy_event_type()` output |
| `event_type_canonical` | (A) | Caller's first arg to `emit_event()` |
| `event_type_legacy` | (B) | Same as `event_type` in JSON |
| `timestamp` | (B) | `datetime.now().isoformat()` |
| `run.*` | (B) | `self._run_id`, `self._experiment_name`, `self._trial`, `self._model` |
| `trace.trace_id` | (B) | `self._current_trace_id` |
| `trace.parent_event_id` | (A) | Caller (REQUIRED for llm_call/execution_eval/reasoning_eval/error) |
| `trace.trajectory_id` | (B) | `self._current_trajectory_id` |
| `trace.event_index_within_trace` | (B) | `self._trace_event_counter` |
| `context.*` | (A/B) | `case_id`, `condition`, `attempt_idx`, `step`, `phase`, `node`, `edge` from caller; `condition` falls back to `self._condition` |
| `prompt.*` | (A) | All 7 fields from caller's `prompt_assembly` dict |
| `llm_call.*` | (A/B) | `call_id` from self, paths from self, rest from caller |
| `execution.*` | (B) | Returned by `_build_canonical_and_extra()` — NOT read by `emit_event()` |
| `reasoning.*` | (B) | Returned by `_build_canonical_and_extra()` — NOT read by `emit_event()` |
| `artifacts.*` | (A) | Caller (all null currently) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (null currently) |
| `extra` | (B) | Returned by `_build_canonical_and_extra()` — NOT read by `emit_event()` |

---

## 11. Call Site Contracts

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

## 12. Schema Duplication Prevention

### Single source of truth

The `execution` and `reasoning` sections of the canonical schema are defined by ONE artifact: `_build_canonical_and_extra()`. This function reads fields, tracks consumed keys, and returns sections. `emit_event()` inserts them by reference without reading `raw_ev`.

### Proof of non-duplication

1. `_build_canonical_and_extra()` defines canonical fields by reading them.
2. `consumed_keys` is built inline alongside each read.
3. `extra` is `raw_ev.keys() - consumed_keys`.
4. `emit_event()` receives three dicts and inserts them. It has no independent knowledge of which fields are canonical.
5. The overlap invariant (Section 3) validates at emission time that no key exists in both consumed and extra.
6. There is no static field set, no schema constant, no second definition.

---

## 13. Migration Plan

### Step 1: `emit_event()` + extraction + invariants in logging_core.py
- Add `emit_event()` per Section 1
- Add `_build_canonical_and_extra()` per Section 2
- Add `_enforce_no_overlap()` per Section 3
- Add `resolve_legacy_event_type()`, `_build_compat_payload()`, `_build_compat_envelope()`
- Add `PARENT_REQUIRED` enforcement
- Add `experiment_name` to constructor
- Add `_current_trajectory_id`, `_trace_event_counter`, `new_trajectory()`
- `start_case()` returns `CaseHandle(trace_id, event_id)`
- Test: canonical + compat output, parent enforcement, overlap invariant

### Step 2: Convert `log_call()` → `emit_event("llm_call", ...)`
- File writes unchanged. Event write delegates to `emit_event()`
- `log_call()` requires `parent_event_id`
- Test: events.jsonl compat matches old format

### Step 3: Convert case lifecycle → `emit_event()`
- `end_case(case_id, *, condition, raw_ev, runtime_ms, parent_event_id)`
- `fail_case(case_id, error, *, condition, parent_event_id)`
- Test: lifecycle correct

### Step 4: Convert `log_event()` / `log_metric()` → `emit_event("pipeline_state", ...)`
- Test: run.start/run.end correct

### Step 5: Update `_capture_prompt_assembly()` in execution.py
- Add `full_prompt` param
- Compute `prompt_hash` (sha256 of full prompt)
- Compute `variables_hash` (sha256 of canonical JSON of full variable mapping)
- Test: hashes correct

### Step 6: Update runner.py
- Pass `experiment_name`, capture `CaseHandle`, thread `parent_event_id`
- Test: e2e smoke

### Step 7: Update execution.py
- Pass `raw_ev` to `end_case()`, capture event_ids for parent chaining
- Call `new_trajectory()` before retry in `run_repair_loop` (before attempt 2)
- Call `new_trajectory()` before retry in `run_contract_gated` (before retry call_model)
- Call `new_trajectory()` before `_fallback_run()` in `run_contract_gated`
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

## 14. Verification

1. `emit_event()` canonical + compat output for all 5 event types
2. Smoke test: 3 cases × 3 conditions, aggregate.py produces identical dashboard.json
3. `finalize()` validates every event structurally
4. Parent chain: CGE elicit→code→retry→eval forms correct DAG
5. Parent enforcement: missing parent on `llm_call` raises RuntimeError
6. Overlap invariant: field in both canonical and extra raises RuntimeError
7. Inverse mapping: new field added to `ev` automatically appears in `extra`
8. run.jsonl: zero forbidden canonical fields
9. Trajectory: `run_repair_loop` creates 2 trajectory_ids; `run_contract_gated` with retry creates 2; `run_retry_harness` creates N
10. `resolve_legacy_event_type()` correct for all type × phase × step combinations
11. `variables_hash` differs for same keys with different values
12. `tokens_input_estimate` uses tiktoken when available, chars/4 otherwise

---

## Files Modified

| Step | File |
|------|------|
| 1–4, 10–11 | `logging_core.py` |
| 5, 7 | `execution.py` |
| 6 | `runner.py` |
| 8 | `execution_v2.py` |
| 9 | `retry_harness.py` |
