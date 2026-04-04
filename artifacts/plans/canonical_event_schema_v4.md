# Plan: Canonical Event Schema v4 — Final

## Context

The logging system passes `RunLogger` explicitly through the call stack. Schema knowledge leaks outside `logging_core`: `_build_metrics_payload()` in `execution.py` constructs event dicts, `log_call()` and `log_run()` each build independent record formats. This plan introduces `RunLogger.emit_event()` as the single canonical emission point.

---

## 1. Architecture

### Single emission function

`RunLogger.emit_event(event_type, *, ...keyword_args) -> int` is the ONLY function that writes to events.jsonl. All other methods are thin wrappers.

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

`event_type` is the canonical type. `event_type_legacy` is the backward-compat mapping. All 14 sections are ALWAYS present.

---

## 2. Trajectory ID — Control-Flow Based

### Rule

A new `trajectory_id` is created whenever execution re-enters generation after evaluation, branches, loops, or follows a fallback path. The rule is defined by control flow structure, not by function name or condition type.

### Formal definition

`new_trajectory()` MUST be called immediately before ANY of:
1. A generation call that follows an evaluation of a prior generation (re-entry after feedback)
2. A fallback path after a failure (e.g., CGE contract parse failure → fallback)
3. A retry iteration in any loop (k > 0)

`new_trajectory()` MUST NOT be called:
1. Before the first generation call in a case (handled by `start_case()`)
2. Between a generation call and its immediate evaluation (same trajectory)
3. Between generation and classification within a single pipeline pass (same trajectory)

### Application to each execution path

| Path | Trajectory creation points | Count |
|---|---|---|
| `run_single` | `start_case()` creates first. No re-entry. | 1 |
| `run_repair_loop` | `start_case()` creates first. `new_trajectory()` before attempt 2 (re-entry after evaluation). | 2 |
| `run_contract_gated` | `start_case()` creates first. `new_trajectory()` before retry generation (re-entry after gate evaluation). | 1 or 2 |
| `run_contract_gated` fallback | `start_case()` creates first. `new_trajectory()` before fallback eval (fallback path). | 2 |
| `run_leg_reduction` | `start_case()` creates first. No re-entry. | 1 |
| `run_v2` | `start_case()` creates first. No re-entry. | 1 |
| `run_retry_harness` | `start_case()` creates first. `new_trajectory()` before each iteration k > 0 (re-entry after evaluation). | 1 + (iterations - 1) |
| Graph runner (future) | `start_case()` creates first. `new_trajectory()` at each DAG branch point or feedback loop entry. | varies |

### Implementation

```python
def new_trajectory(self) -> str:
    """Create a new trajectory within the current trace. Returns trajectory_id.
    Raises RuntimeError if no trace is active."""
    if self._current_trace_id is None:
        raise RuntimeError("new_trajectory() requires an active trace")
    self._current_trajectory_id = uuid.uuid4().hex
    return self._current_trajectory_id
```

`start_case()` creates the first trajectory. `new_trajectory()` creates subsequent ones. `end_case()` / `fail_case()` clear both.

---

## 3. Parent Event ID — Strict Enforcement

### Events that REQUIRE parent_event_id (non-null)

```python
PARENT_REQUIRED = frozenset({"llm_call", "execution_eval", "reasoning_eval", "error"})
```

Enforcement in `emit_event()`:

```python
if event_type in PARENT_REQUIRED and parent_event_id is None:
    raise RuntimeError(
        f"parent_event_id is required for event_type={event_type!r} "
        f"but was None. case_id={case_id}, condition={condition}."
    )
```

### Parent source for every event in every execution path

| Path | Event | parent_event_id |
|---|---|---|
| **run_single** | `llm_call` (gen) | `case_start_eid` from `start_case()` |
| **run_single** | `execution_eval` | `gen_eid` from `log_call()` |
| **run_repair_loop** | `llm_call` (attempt 1) | `case_start_eid` |
| **run_repair_loop** | `execution_eval` (attempt 1, if pass) | `gen1_eid` |
| **run_repair_loop** | `llm_call` (attempt 2) | `gen1_eid` |
| **run_repair_loop** | `execution_eval` (final) | `gen2_eid` |
| **run_contract_gated** | `llm_call` (elicit) | `case_start_eid` |
| **run_contract_gated** | `llm_call` (code gen) | `elicit_eid` |
| **run_contract_gated** | `llm_call` (retry) | `code_gen_eid` |
| **run_contract_gated** | `execution_eval` | last `llm_call` eid |
| **run_contract_gated fallback** | `execution_eval` | `elicit_eid` |
| **run_contract_gated fallback** | `error` (if exception) | `case_start_eid` |
| **run_leg_reduction** | `llm_call` (gen) | `case_start_eid` |
| **run_leg_reduction** | `execution_eval` | `gen_eid` |
| **run_v2** | `llm_call` (gen) | `case_start_eid` |
| **run_v2** | `llm_call` (classify) | `gen_eid` |
| **run_v2** | `execution_eval` | `classify_eid` (or `gen_eid` if no classifier) |
| **run_retry_harness** | `llm_call` (k=0) | `case_start_eid` |
| **run_retry_harness** | `llm_call` (k>0) | previous iteration's `eval_eid` |
| **run_retry_harness** | `execution_eval` (final) | last `llm_call` eid |
| **fail_case** (any path) | `error` | `case_start_eid` |

`pipeline_state` events (case.start, run.start, run.end): `parent_event_id` is `null`. Not in `PARENT_REQUIRED`.

---

## 4. Prompt Hash — Computed by Caller

logging_core records prompt identity fields verbatim. It does not compute any of them.

| Field | Computed by | How |
|---|---|---|
| `prompt_hash` | `_capture_prompt_assembly()` in execution.py | `hashlib.sha256(full_prompt_string.encode()).hexdigest()` |
| `prompt_family` | `_capture_prompt_assembly()` | `condition` string |
| `prompt_name` | `_capture_prompt_assembly()` | `rendered.plan_hash` |
| `prompt_version` | `_capture_prompt_assembly()` | `config.experiment.name` |
| `template_id` | `_capture_prompt_assembly()` | `rendered.final_prompt_hash` |
| `variables_hash` | `_capture_prompt_assembly()` | `hashlib.sha256(",".join(sorted(rendered.variables_used)).encode()).hexdigest()` |
| `tokens_input_estimate` | `_estimate_prompt_tokens()` in execution.py | tiktoken with char/4 fallback |

---

## 5. Extra Field Extraction — Zero Static Sets

### The problem with static sets

A static `_CANONICAL_RAW_EV_FIELDS` duplicates the schema definition: the extraction logic already defines which fields it reads. Maintaining a separate set that mirrors the extraction creates two sources of truth that drift.

### Solution: extraction-as-definition

The extraction functions `_extract_execution()` and `_extract_reasoning()` are the single source of truth for which fields are canonical. The `extra` computation uses these functions' outputs to determine what was consumed.

### Algorithm

```python
def _build_canonical_and_extra(self, raw_ev: dict, runtime_ms: float | None) -> tuple[dict, dict, dict]:
    """Extract canonical sections from raw_ev. Return (execution, reasoning, extra).

    The set of canonical fields is defined IMPLICITLY by what this function reads.
    extra = raw_ev minus consumed keys. No static field list exists.
    """
    consumed_keys = set()

    # --- execution section ---
    exec_data = raw_ev.get("execution", {})
    consumed_keys.add("execution")
    execution = {
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
    reasoning = {
        "evaluated": raw_ev.get("reasoning_correct") is not None,
        "reasoning_correct": raw_ev.get("reasoning_correct"),
        "failure_type": raw_ev.get("failure_type"),
        "confidence": raw_ev.get("confidence"),
    }
    consumed_keys.update({"reasoning_correct", "failure_type", "confidence"})

    # --- identity fields consumed by context (not stored in execution/reasoning) ---
    consumed_keys.update({"condition", "operator_used", "num_attempts", "alignment"})

    # --- extra: everything NOT consumed ---
    extra = {k: v for k, v in raw_ev.items() if k not in consumed_keys}

    return execution, reasoning, extra
```

### Invariants

1. `consumed_keys` is built INLINE as each field is read. Adding a new canonical field means reading it in the extraction code AND adding it to `consumed_keys` in the same block — one edit, one location.
2. `extra = raw_ev.keys() - consumed_keys` — guaranteed. No field is silently dropped.
3. Zero static sets exist anywhere. The extraction IS the definition.
4. If a developer reads a field from `raw_ev` for a canonical section but forgets to add it to `consumed_keys`, it appears in BOTH the canonical section AND `extra`. This is detectable: `finalize()` validates that `consumed_keys ∩ extra.keys() == ∅` for every event by re-running extraction on stored raw_ev. (Implementation: store raw_ev keys in event for audit.)

### Schema drift prevention

The schema is defined in exactly one place: `_build_canonical_and_extra()`. There is no second representation. The canonical schema documentation (this plan, docstrings) describes the output of this function. If extraction changes, the schema changes. There is no synchronization problem because there is only one source.

---

## 6. Compatibility Envelope

### Event type semantics

`event_type` is the canonical type. `event_type_legacy` is the backward-compat mapping. This is enforced by the schema definition and by `emit_event()`:

```python
record = {
    "event_type": event_type,                                    # canonical (primary)
    "event_type_legacy": resolve_legacy_event_type(event_type, phase, step),  # compat (secondary)
    ...
}
```

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

### Compat envelope in events.jsonl

Every written event has flat legacy keys at top level for aggregate.py:

```python
flat_compat = {
    "event_type": resolve_legacy_event_type(event_type, phase, step),  # aggregate.py reads this
    "model": self._model,
    "condition": effective_condition,
    "case_id": case_id,
    "trace_id": self._current_trace_id,
    "trial": self._trial,
    "phase": phase,
    "event_id": event_id,
    "payload": _build_compat_payload(record),
}
```

The full record merges `flat_compat` with the canonical structure. aggregate.py reads the flat keys. New consumers read the canonical sections.

### `_build_compat_payload(record) -> dict`

- For `llm_call`: `{"call_id": ..., "latency_ms": ..., "prompt_length": ..., "response_length": ..., "error": ...}`
- For `execution_eval`: `{"pass": ..., "score": ..., "failure_type": ..., **extra}`
- For `error`: `{"error": ...}`
- For `pipeline_state`: `{}`

---

## 7. run.jsonl Contract

### Allowed fields (exhaustive)

| Field | Purpose |
|---|---|
| `canonical_event_id` | Cross-reference to events.jsonl |
| `run_id` | Identity for standalone debug |
| `trace_id` | Identity |
| `case_id` | Identity |
| `condition` | Identity |
| `timestamp` | When written |
| `prompt_length` | Debug |
| `raw_response_length` | Debug |
| `parsed_reasoning` | Truncated reasoning (2000 chars max) |
| `parsed_code_length` | Length of extracted code |
| `parse_error` | Parser error string |
| `response_format` | Which parser tier matched |
| `data_lineage` | Parse/reconstruct lineage trace |

### Forbidden

run.jsonl MUST NOT contain: `pass`, `score`, `ran`, `tests_run`, `tests_passed`, `reasoning_correct`, `failure_type`, `confidence`, `latency_ms`, `call_id`, `prompt_hash`, `tokens_input_estimate`, `temperature`, `max_tokens`, or any other field from the canonical `execution`, `reasoning`, `prompt`, `llm_call`, `metrics`, or `artifacts` sections.

### `log_run()` signature

```python
def log_run(self, case_id: str, condition: str, prompt: str,
            raw_output: str, parsed: dict, canonical_event_id: int) -> None:
```

Accepts `parsed` (for debug extraction). Does NOT accept `ev`. Writes only allowed fields.

---

## 8. Field Mapping Table

(A) = caller passes, (B) = RunLogger computes from internal state, (C) = constant/config

| Field | Class | Source |
|---|---|---|
| `schema_version` | (C) | `"1.0"` |
| `event_id` | (B) | `self._event_counter` |
| `event_type` | (A) | Caller arg (canonical) |
| `event_type_legacy` | (B) | `resolve_legacy_event_type()` |
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
| `execution.*` | (A/B) | Extracted from `raw_ev` by `_build_canonical_and_extra()` |
| `reasoning.*` | (A/B) | Extracted from `raw_ev` by `_build_canonical_and_extra()` |
| `artifacts.*` | (A) | Caller (all null currently) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (null currently) |
| `extra` | (B) | `raw_ev.keys() - consumed_keys` via `_build_canonical_and_extra()` |

---

## 9. Call Site Contracts

execution.py, execution_v2.py, runner.py, llm.py, retry_harness.py MUST NOT construct event dictionaries.

### runner.py
- `RunLogger(run_dir, run_id, model, condition=None, trial, experiment_name=...)`
- `handle = logger.start_case(cid)` → `CaseHandle(trace_id, event_id)`
- Passes `handle.event_id` to execution functions as `case_start_eid`
- `logger.fail_case(cid, error_str, condition=condition, parent_event_id=handle.event_id)`

### execution.py
- `gen_eid = logger.log_call(...)` — captures event_id
- `end_eid = logger.end_case(cid, condition=condition, raw_ev=ev, runtime_ms=..., parent_event_id=gen_eid)`
- `logger.log_run(cid, condition, prompt, raw_output, parsed, canonical_event_id=end_eid)`
- Does NOT call `_build_metrics_payload()` — deleted
- Does NOT select fields for extra — automatic via `_build_canonical_and_extra()`

### llm.py
- `_log_call_if_logger()` passes raw args + `parent_event_id` to `logger.log_call()`

---

## 10. Schema Duplication Prevention

### Single source of truth

The canonical schema is defined by ONE artifact: the `_build_canonical_and_extra()` function in `logging_core.py`. This function:
- Reads specific fields from `raw_ev` (defining the execution and reasoning sections)
- Tracks consumed keys inline
- Returns extra as everything unconsumed

There is no second list, no second definition, no schema constant to synchronize.

### Proof of non-duplication

1. `_build_canonical_and_extra()` defines which fields are canonical by reading them.
2. `consumed_keys` is built inline alongside each read — not in a separate constant.
3. `extra` is derived by set difference — not by a whitelist.
4. The schema documentation in this plan describes the OUTPUT of `_build_canonical_and_extra()`. If the function changes, the documentation is stale but the code is authoritative. The function IS the schema.
5. `finalize()` validates structural completeness by checking all 14 top-level keys exist in every event. This validates the output format, not a separate schema definition.

---

## 11. Migration Plan

### Step 1: `emit_event()` + extraction in logging_core.py
- Add `emit_event()` with full canonical construction
- Add `_build_canonical_and_extra()` — extraction-as-definition
- Add `resolve_legacy_event_type()` — total function
- Add `_build_compat_payload()` — legacy payload builder
- Add `_build_compat_envelope()` — flat legacy keys
- Add `PARENT_REQUIRED` enforcement
- Add `experiment_name` to constructor
- Add `_current_trajectory_id`, `_trace_event_counter`
- Add `new_trajectory()`, update `start_case()` to return `CaseHandle`
- Test: emit_event canonical + compat output, parent enforcement

### Step 2: Convert `log_call()` → `emit_event("llm_call", ...)`
- File writes unchanged. Event write delegates to `emit_event()`
- Add `parent_event_id` parameter to `log_call()`
- Test: events.jsonl compat matches old format

### Step 3: Convert case lifecycle → `emit_event()`
- `end_case(case_id, *, condition, raw_ev, runtime_ms, parent_event_id)`
- `fail_case(case_id, error, *, condition, parent_event_id)`
- `start_case()` returns `CaseHandle(trace_id, event_id)`
- Test: lifecycle events correct

### Step 4: Convert `log_event()` / `log_metric()` → `emit_event("pipeline_state", ...)`
- Test: run.start/run.end correct

### Step 5: Update `_capture_prompt_assembly()` in execution.py
- Add `full_prompt` param, compute `prompt_hash` and `variables_hash`
- Test: hashes correct

### Step 6: Update runner.py
- Pass `experiment_name`, capture `CaseHandle`, thread `parent_event_id`
- Test: e2e smoke

### Step 7: Update execution.py
- Pass `raw_ev` to `end_case()`, capture event_ids for parent chaining
- Call `new_trajectory()` before attempt 2 in `run_repair_loop`
- Call `new_trajectory()` before retry in `run_contract_gated`
- Delete `_build_metrics_payload()`
- Test: all v1 conditions

### Step 8: Update execution_v2.py
- Same pattern. Chain: `gen_eid → classify_eid → end_eid`
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

## 12. Verification

1. `emit_event()` canonical + compat output for all 5 event types
2. Smoke test: 3 cases × 3 conditions, aggregate.py produces identical dashboard.json
3. `finalize()` validates every event against structural requirements
4. Parent chain: CGE elicit→code→retry→eval forms correct DAG
5. Parent enforcement: missing parent on `llm_call` raises RuntimeError
6. Inverse mapping: new field added to `ev` automatically appears in `extra`
7. run.jsonl: zero forbidden canonical fields
8. Trajectory: `run_repair_loop` creates 2 trajectory_ids, `run_retry_harness` creates N
9. `resolve_legacy_event_type()` correct for all type × phase × step combinations
10. No static canonical field set exists anywhere in codebase (grep verification)

---

## Files Modified

| Step | File |
|------|------|
| 1–4, 10–11 | `logging_core.py` |
| 5, 7 | `execution.py` |
| 6 | `runner.py` |
| 8 | `execution_v2.py` |
| 9 | `retry_harness.py` |
