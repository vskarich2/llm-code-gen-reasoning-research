# Plan: Canonical Event Schema v3 — Final

## Context

The logging system passes `RunLogger` explicitly through the call stack. Schema knowledge leaks outside `logging_core`: `_build_metrics_payload()` in `execution.py` constructs event dicts, `log_call()` and `log_run()` each build independent record formats. This plan introduces `RunLogger.emit_event()` as the single canonical emission point. Every event conforms to a structured schema. Zero schema logic exists outside `logging_core`.

---

## 1. Architecture

### Single emission function

**`RunLogger.emit_event(event_type, *, ...keyword_args) -> int`**

This is the ONLY function that writes to events.jsonl. All other methods (`log_call`, `end_case`, `start_case`, `fail_case`, `log_metric`, `log_event`) are thin wrappers that call `emit_event()`.

`emit_event()`:
1. Constructs the full canonical record from keyword args + `self._*` state
2. Assigns `event_id` (monotonic), `timestamp`, `event_index_within_trace`
3. Validates: all 14 sections present, parent_event_id enforcement, trace requirements
4. Builds backward-compat envelope for aggregate.py
5. Writes single JSON line to events.jsonl
6. Returns `event_id`

### Canonical schema

```
{
  "schema_version": "1.0",
  "event_id": int,
  "event_type": "llm_call | execution_eval | reasoning_eval | pipeline_state | error",
  "timestamp": "ISO-8601",
  "run":       { run_id, experiment_name, trial, model },
  "trace":     { trace_id, parent_event_id, trajectory_id, event_index_within_trace },
  "context":   { case_id, condition, attempt_idx, step, phase, node, edge },
  "prompt":    { prompt_family, prompt_name, prompt_version, prompt_hash, template_id, variables_hash, tokens_input_estimate },
  "llm_call":  { call_id, provider, model, temperature, max_tokens, tokens_output_estimate, latency_ms, status, error_type, request_path, response_path, flat_path },
  "execution": { ran, passed, score, tests_run, tests_passed, runtime_ms, error },
  "reasoning": { evaluated, reasoning_correct, failure_type, confidence },
  "artifacts": { code_path, diff_path, stdout_path, stderr_path },
  "metrics":   { cumulative_calls, cumulative_cost },
  "extra":     { ... }
}
```

All 14 sections ALWAYS present. Inapplicable fields are `null`.

---

## 2. Fix 1: trajectory_id — Explicit Creation and Propagation

### Definition

`trajectory_id` is a UUID-hex string that identifies one linear execution path within a case trace. A trace contains one or more trajectories. Each trajectory is a sequence of causally linked events with no branches.

### Creation rules

| Execution path | When trajectory_id is created | How |
|---|---|---|
| `run_single` | At case start | `trajectory_id = uuid.uuid4().hex` created inside `start_case()` stored as `self._current_trajectory_id` |
| `run_repair_loop` | At case start (attempt 1), and at retry start (attempt 2) | `start_case()` creates first trajectory. Caller creates new trajectory via `logger.new_trajectory()` before attempt 2. |
| `run_contract_gated` | At case start (one trajectory for entire CGE pipeline: elicit→code→gate→retry→eval) | Single trajectory. CGE is linear (no branch point — retry is deterministic on gate failure). |
| `run_contract_gated` fallback | At case start | Single trajectory (fallback is a separate linear path). |
| `run_leg_reduction` | At case start | Single trajectory. |
| `run_v2` | At case start | Single trajectory. |
| `run_retry_harness` | At case start (iteration 0), and at each retry iteration start (k>0) | `start_case()` creates first. Caller creates new trajectory via `logger.new_trajectory()` at top of each retry iteration `k > 0`. |
| Graph runner (future) | At each DAG node that creates a branch | Caller calls `logger.new_trajectory()` at branch point. |

### `new_trajectory()` method

```
def new_trajectory(self) -> str:
    """Create a new trajectory within the current trace. Returns trajectory_id."""
    self._current_trajectory_id = uuid.uuid4().hex
    return self._current_trajectory_id
```

### Propagation

`trajectory_id` is injected into every event by `emit_event()` from `self._current_trajectory_id`. Callers never pass trajectory_id — they call `new_trajectory()` to branch, and `emit_event()` reads the current value.

### Lifecycle

- Created in `start_case()` (first trajectory)
- Optionally rotated by `new_trajectory()` (new trajectory within same trace)
- Cleared in `end_case()` / `fail_case()` along with trace_id

---

## 3. Fix 2: parent_event_id — Strict Enforcement, Zero Fallback

### Events that REQUIRE parent_event_id (non-null)

| event_type | parent_event_id required | Enforcement |
|---|---|---|
| `llm_call` | YES | `emit_event()` raises `RuntimeError` if `parent_event_id is None` |
| `execution_eval` | YES | `emit_event()` raises `RuntimeError` if `parent_event_id is None` |
| `reasoning_eval` | YES | `emit_event()` raises `RuntimeError` if `parent_event_id is None` |
| `error` | YES | `emit_event()` raises `RuntimeError` if `parent_event_id is None` |
| `pipeline_state` | NO | `parent_event_id` is `null` for run.start, run.end, case.start. Non-null for graph nodes (caller provides). |

### Enforcement logic inside `emit_event()`

```
PARENT_REQUIRED = frozenset({"llm_call", "execution_eval", "reasoning_eval", "error"})

if event_type in PARENT_REQUIRED and parent_event_id is None:
    raise RuntimeError(
        f"parent_event_id is required for event_type={event_type!r} "
        f"but was None. case_id={case_id}, condition={condition}. "
        f"Caller MUST pass the event_id of the causal predecessor."
    )
```

### What each caller passes as parent_event_id

| Caller | Event | parent_event_id source |
|---|---|---|
| `run_single` | `llm_call` (generation) | `case_start_event_id` (returned from `start_case()`) |
| `run_single` | `execution_eval` (case.end) | `gen_call_event_id` (returned from `log_call()`) |
| `run_repair_loop` | `llm_call` (attempt 1) | `case_start_event_id` |
| `run_repair_loop` | `llm_call` (attempt 2) | `eval_1_event_id` (from first end_case / interim eval) |
| `run_repair_loop` | `execution_eval` | last `llm_call` event_id |
| `run_contract_gated` | `llm_call` (elicit) | `case_start_event_id` |
| `run_contract_gated` | `llm_call` (code gen) | `elicit_event_id` |
| `run_contract_gated` | `llm_call` (retry) | `code_gen_event_id` |
| `run_contract_gated` | `execution_eval` | last `llm_call` event_id |
| `run_v2` | `llm_call` (generation) | `case_start_event_id` |
| `run_v2` | `llm_call` (classification) | `gen_event_id` |
| `run_v2` | `execution_eval` | `classify_event_id` (or `gen_event_id` if no classifier) |
| `run_retry_harness` | `llm_call` (iteration k=0) | `case_start_event_id` |
| `run_retry_harness` | `llm_call` (iteration k>0) | previous iteration's `execution_eval` event_id |
| `run_retry_harness` | `execution_eval` (final) | last `llm_call` event_id |
| `fail_case` (exception) | `error` | `case_start_event_id` |

### Return value contract

Every wrapper that writes events returns `event_id`:
- `start_case(cid) -> CaseHandle(trace_id: str, event_id: int)`
- `log_call(...) -> int` (event_id of the llm_call event)
- `end_case(...) -> int` (event_id of the execution_eval event)
- `fail_case(...) -> int` (event_id of the error event)
- `emit_event(...) -> int`

Callers capture return values and thread them as `parent_event_id` to subsequent calls.

---

## 4. Fix 3: prompt_hash — Computed by Caller, Not Logger

### Rule

`logging_core` records prompt_hash. It does not compute it. The prompt system (`_capture_prompt_assembly` in execution.py, and `assembly_engine.py`) computes all prompt identity fields.

### Field ownership

| Field | Computed by | Passed to emit_event as |
|---|---|---|
| `prompt_hash` | Caller. `hashlib.sha256(full_prompt_string.encode()).hexdigest()` computed in `_capture_prompt_assembly()` after `assembly_engine.build()`. | `prompt_hash` keyword arg |
| `prompt_family` | Caller. `condition` string from build_prompt. | `prompt_family` keyword arg |
| `prompt_name` | Caller. `rendered.plan_hash` from assembly_engine. | `prompt_name` keyword arg |
| `prompt_version` | Caller. `config.experiment.name` from experiment_config. | `prompt_version` keyword arg |
| `template_id` | Caller. `rendered.final_prompt_hash` from assembly_engine. | `template_id` keyword arg |
| `variables_hash` | Caller. `hashlib.sha256(",".join(sorted(rendered.variables_used)).encode()).hexdigest()` in `_capture_prompt_assembly()`. | `variables_hash` keyword arg |
| `tokens_input_estimate` | Caller. `_estimate_prompt_tokens(prompt, model)` in execution.py. | `tokens_input_estimate` keyword arg |

### Updated `_capture_prompt_assembly()`

```python
def _capture_prompt_assembly(rendered, variables: dict, condition: str, full_prompt: str) -> dict:
    import hashlib
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
            ",".join(sorted(rendered.variables_used)).encode()
        ).hexdigest(),
    }
```

`emit_event()` stores these values verbatim in the `prompt` section. Zero computation inside logging_core.

---

## 5. Fix 4: Extra Field Handling — Inverse Mapping, Zero Whitelists

### Algorithm

`emit_event()` defines the set of canonical fields it extracts from `raw_ev`. Everything else goes into `extra`.

```python
# Constant: fields that emit_event() reads from raw_ev for canonical sections
_CANONICAL_RAW_EV_FIELDS = frozenset({
    "pass", "score", "execution", "reasoning_correct", "failure_type",
    "confidence", "num_attempts", "operator_used", "condition",
    "alignment",
})

def _partition_raw_ev(raw_ev: dict) -> tuple[dict, dict]:
    """Split raw_ev into (canonical_fields, extra_fields).

    canonical_fields: fields consumed by canonical schema sections.
    extra_fields: EVERYTHING ELSE. No filtering. No whitelists.
    """
    canonical = {}
    extra = {}
    for k, v in raw_ev.items():
        if k in _CANONICAL_RAW_EV_FIELDS:
            canonical[k] = v
        else:
            extra[k] = v
    return canonical, extra
```

### Guarantees

- New fields added to `raw_ev` by any execution path automatically land in `extra` — zero maintenance.
- No field is silently dropped. `canonical ∪ extra == raw_ev` (set identity).
- `_CANONICAL_RAW_EV_FIELDS` is updated ONLY when a field moves INTO a canonical section (requires schema version bump).
- The set is a `frozenset` constant in `logging_core.py` — immutable, auditable.

### What the canonical sections extract

```python
exec_data = canonical.get("execution", {})
execution_section = {
    "ran": exec_data.get("ran"),
    "passed": canonical.get("pass"),
    "score": canonical.get("score"),
    "tests_run": exec_data.get("total_tests"),
    "tests_passed": exec_data.get("tests_passed"),
    "runtime_ms": runtime_ms,  # from caller param, not raw_ev
    "error": exec_data.get("error"),
}
reasoning_section = {
    "evaluated": canonical.get("reasoning_correct") is not None,
    "reasoning_correct": canonical.get("reasoning_correct"),
    "failure_type": canonical.get("failure_type"),
    "confidence": canonical.get("confidence"),
}
```

---

## 6. Fix 5: Compatibility Layer — Total Function

### `resolve_legacy_event_type(event_type: str, phase: str | None, step: str | None) -> str`

This is a pure function. It handles ALL inputs. It never returns null.

```python
def resolve_legacy_event_type(event_type: str, phase: str | None, step: str | None) -> str:
    """Map canonical event_type to legacy event_type. Total function — always returns a string."""
    if event_type == "llm_call":
        if phase == "classification":
            return "call.classify"
        if phase == "generation":
            return "call.generate"
        return "call.other"

    if event_type == "execution_eval":
        return "case.end"

    if event_type == "reasoning_eval":
        return "case.end"  # reasoning was part of case.end in legacy

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
        return "pipeline_state"  # no legacy equivalent — new events

    return event_type  # unknown type passes through unchanged
```

### Compat envelope construction

Every event written to events.jsonl includes BOTH canonical structure AND flat legacy keys:

```python
{
    # Legacy flat keys (aggregate.py reads these)
    "event_type": resolve_legacy_event_type(event_type, phase, step),
    "model": run.model,
    "condition": context.condition,
    "case_id": context.case_id,
    "trace_id": trace.trace_id,
    "trial": run.trial,
    "phase": context.phase,
    "event_id": event_id,
    "payload": _build_compat_payload(canonical_record),

    # Canonical structure
    "schema_version": "1.0",
    "event_type_canonical": event_type,
    "run": {...},
    "trace": {...},
    "context": {...},
    ...all 14 sections...
}
```

### `_build_compat_payload(record) -> dict`

Maps canonical sections back to the flat payload format aggregate.py reads:
- For `llm_call`: `{"call_id": llm_call.call_id, "latency_ms": llm_call.latency_ms, "prompt_length": prompt.tokens_input_estimate, "response_length": llm_call.tokens_output_estimate, "error": llm_call.error_type}`
- For `execution_eval` / case.end: `{"pass": execution.passed, "score": execution.score, "failure_type": reasoning.failure_type, **extra}`
- For `error` / case.failed: `{"error": execution.error}`
- For `pipeline_state`: `{}` (case.start had empty payload)

---

## 7. Fix 6: run.jsonl — Strict Contract

### Allowed fields (exhaustive list)

```python
RUN_JSONL_ALLOWED_FIELDS = {
    "canonical_event_id",    # cross-reference to events.jsonl
    "run_id",                # identity (redundant with events.jsonl but needed for standalone debug)
    "trace_id",              # identity
    "case_id",               # identity
    "condition",             # identity
    "timestamp",             # when this record was written
    "prompt_length",         # debug: how long was the prompt
    "raw_response_length",   # debug: how long was the response
    "parsed_reasoning",      # debug: truncated reasoning text (first 2000 chars)
    "parsed_code_length",    # debug: length of extracted code
    "parse_error",           # debug: parser error string
    "response_format",       # debug: which parser tier matched
    "data_lineage",          # debug: lineage trace through parse/reconstruct
}
```

### Forbidden rule

`run.jsonl` records MUST NOT contain any field that exists in the canonical schema sections (`execution`, `reasoning`, `prompt`, `llm_call`, `metrics`, `artifacts`). These fields are exclusively in events.jsonl.

Specifically forbidden: `pass`, `score`, `ran`, `tests_run`, `tests_passed`, `reasoning_correct`, `failure_type`, `confidence`, `latency_ms`, `call_id`, `prompt_hash`, `tokens_input_estimate`.

### Implementation

`log_run()` accepts `canonical_event_id: int` and the raw `prompt`, `raw_output`, `parsed` dict. It extracts ONLY the allowed debug fields. It does not accept or write `ev` (the evaluation dict).

```python
def log_run(self, case_id: str, condition: str, prompt: str,
            raw_output: str, parsed: dict, canonical_event_id: int) -> None:
    record = {
        "canonical_event_id": canonical_event_id,
        "run_id": self._run_id,
        "trace_id": self._current_trace_id,
        "case_id": case_id,
        "condition": condition,
        "timestamp": datetime.now().isoformat(),
        "prompt_length": len(prompt),
        "raw_response_length": len(raw_output),
        "parsed_reasoning": str(parsed.get("reasoning", ""))[:2000],
        "parsed_code_length": len(parsed.get("code") or ""),
        "parse_error": parsed.get("parse_error"),
        "response_format": parsed.get("response_format"),
        "data_lineage": parsed.get("data_lineage"),
    }
    # write to run.jsonl (append, fsync)
```

---

## 8. Field Mapping Table

Classification: (A) passed from caller, (B) computed in RunLogger, (C) constant/config

| Field | Class | Source |
|---|---|---|
| `schema_version` | (C) | `"1.0"` |
| `event_id` | (B) | `self._event_counter` |
| `event_type` | (A) | Caller arg |
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
| `prompt.prompt_family` | (A) | Caller (from `prompt_assembly`) |
| `prompt.prompt_name` | (A) | Caller (from `prompt_assembly`) |
| `prompt.prompt_version` | (A) | Caller (from `prompt_assembly`) |
| `prompt.prompt_hash` | (A) | Caller (sha256 of full prompt, computed in `_capture_prompt_assembly`) |
| `prompt.template_id` | (A) | Caller (from `prompt_assembly`) |
| `prompt.variables_hash` | (A) | Caller (sha256 of sorted variable keys, computed in `_capture_prompt_assembly`) |
| `prompt.tokens_input_estimate` | (A) | Caller (`_estimate_prompt_tokens()`) |
| `llm_call.call_id` | (B) | `self._call_counter` |
| `llm_call.provider` | (C) | `"openai"` |
| `llm_call.model` | (A) | Caller |
| `llm_call.temperature` | (C) | From experiment_config |
| `llm_call.max_tokens` | (C) | From experiment_config |
| `llm_call.tokens_output_estimate` | (A) | Caller |
| `llm_call.latency_ms` | (A) | Caller |
| `llm_call.status` | (A) | Caller |
| `llm_call.error_type` | (A) | Caller |
| `llm_call.request_path` | (B) | `f"calls/{call_id:06d}.json"` |
| `llm_call.response_path` | (B) | Same |
| `llm_call.flat_path` | (B) | `f"calls_flat/{call_id:06d}_{phase}.txt"` |
| `execution.ran` | (A) | From `raw_ev["execution"]["ran"]` via `_partition_raw_ev` |
| `execution.passed` | (A) | From `raw_ev["pass"]` via `_partition_raw_ev` |
| `execution.score` | (A) | From `raw_ev["score"]` via `_partition_raw_ev` |
| `execution.tests_run` | (A) | From `raw_ev["execution"]["total_tests"]` via `_partition_raw_ev` |
| `execution.tests_passed` | (A) | From `raw_ev["execution"]["tests_passed"]` via `_partition_raw_ev` |
| `execution.runtime_ms` | (A) | Caller (elapsed * 1000) |
| `execution.error` | (A) | From `raw_ev["execution"]["error"]` via `_partition_raw_ev` |
| `reasoning.evaluated` | (B) | Derived: `raw_ev.get("reasoning_correct") is not None` |
| `reasoning.reasoning_correct` | (A) | From `raw_ev` via `_partition_raw_ev` |
| `reasoning.failure_type` | (A) | From `raw_ev` via `_partition_raw_ev` |
| `reasoning.confidence` | (A) | From `raw_ev` via `_partition_raw_ev` |
| `artifacts.*` | (A) | Caller (all null currently) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (null currently) |
| `extra` | (A/B) | ALL fields in `raw_ev` NOT in `_CANONICAL_RAW_EV_FIELDS` — automatic via inverse mapping |

---

## 9. Call Site Contracts

**execution.py, execution_v2.py, runner.py, llm.py, retry_harness.py MUST NOT construct event dictionaries.**

### runner.py
- `RunLogger(run_dir, run_id, model, condition=None, trial, experiment_name=...)`
- `handle = logger.start_case(cid)` → captures `handle.event_id` for parent chaining
- `logger.fail_case(cid, error_str, condition=condition, parent_event_id=handle.event_id)`

### execution.py
- `gen_event_id = logger.log_call(...)` — captures returned event_id
- `end_event_id = logger.end_case(cid, condition=condition, raw_ev=ev, runtime_ms=elapsed*1000, parent_event_id=gen_event_id)`
- `logger.log_run(cid, condition, prompt, raw_output, parsed, canonical_event_id=end_event_id)`
- Does NOT call `_build_metrics_payload()` — deleted
- Does NOT select fields for extra — automatic inverse mapping

### llm.py
- `_log_call_if_logger()` passes raw args to `logger.log_call()`
- Unchanged interface

---

## 10. Migration Plan

### Step 1: Add `emit_event()` + inverse mapping to RunLogger
**File:** `logging_core.py`
- Add `emit_event()`, `_partition_raw_ev()`, `resolve_legacy_event_type()`, `_build_compat_payload()`
- Add `_CANONICAL_RAW_EV_FIELDS`, `PARENT_REQUIRED` constants
- Add `experiment_name` to constructor
- Add `_current_trajectory_id`, `_trace_event_counter`, `_current_case_start_event_id`
- Add `new_trajectory()` method
- Add `CaseHandle = namedtuple("CaseHandle", ["trace_id", "event_id"])`
- Test: emit_event produces canonical + compat, parent enforcement works

### Step 2: Convert `log_call()` to delegate to `emit_event()`
**File:** `logging_core.py`
- File writes unchanged. Event write delegates to `emit_event("llm_call", parent_event_id=..., ...)`
- `log_call()` now REQUIRES `parent_event_id` parameter
- Test: events.jsonl compat layer matches old format

### Step 3: Convert case lifecycle to delegate to `emit_event()`
**File:** `logging_core.py`
- `start_case()` returns `CaseHandle`
- `end_case(case_id, *, condition, raw_ev, runtime_ms, parent_event_id)` — new signature
- `fail_case(case_id, error, *, condition, parent_event_id)` — requires parent
- Test: case lifecycle events correct

### Step 4: Convert `log_event()` and `log_metric()` to delegate
**File:** `logging_core.py`
- Thin wrappers around `emit_event("pipeline_state", step=..., ...)`
- Test: run.start/run.end events

### Step 5: Update `_capture_prompt_assembly()` in execution.py
**File:** `execution.py`
- Add `full_prompt` parameter
- Compute `prompt_hash` and `variables_hash` here
- Returns dict with all 6 prompt identity fields
- Test: prompt_assembly contains correct hashes

### Step 6: Update runner.py
**File:** `runner.py`
- Pass `experiment_name` to RunLogger constructor
- `handle = logger.start_case(cid)` — capture CaseHandle
- Pass `handle.event_id` as parent to execution functions
- Test: e2e smoke test

### Step 7: Update execution.py — eliminate `_build_metrics_payload()`
**File:** `execution.py`
- All functions: `end_event_id = logger.end_case(cid, condition=condition, raw_ev=ev, runtime_ms=..., parent_event_id=gen_event_id)`
- All functions: `logger.log_run(cid, condition, prompt, raw_output, parsed, canonical_event_id=end_event_id)`
- Update `log_call()` calls to pass `parent_event_id`
- Delete `_build_metrics_payload()`
- Test: all v1 conditions

### Step 8: Update execution_v2.py
**File:** `execution_v2.py`
- Same pattern. Chain: `gen_eid` → `classify_eid` → `end_eid`
- Test: v2 conditions

### Step 9: Update retry_harness.py
**File:** `retry_harness.py`
- Chain parent_event_id through retry loop
- Call `logger.new_trajectory()` at each retry iteration k>0
- Test: retry conditions with correct parent chain

### Step 10: Update `log_run()` contract
**File:** `logging_core.py`
- New signature: `log_run(case_id, condition, prompt, raw_output, parsed, canonical_event_id)`
- Write ONLY allowed debug fields
- Test: run.jsonl has no forbidden fields

### Step 11: Update `finalize()` and `validate()`
**File:** `logging_core.py`
- Recognize new event types
- Validate canonical schema
- Validate parent_event_id enforcement
- Test: finalize produces correct metrics.json

---

## 11. Verification

1. `emit_event()` produces canonical + compat structure for each of 5 event types
2. Smoke test: 3 cases x 3 conditions, aggregate.py produces identical dashboard.json
3. `finalize()` validates every event against canonical schema
4. Parent chain: verify parent_event_id forms correct DAG for CGE (elicit→code→retry→eval)
5. Parent enforcement: missing parent_event_id on llm_call raises RuntimeError
6. Inverse mapping: new field added to `ev` dict automatically appears in `extra`
7. run.jsonl: contains zero forbidden canonical fields
8. Trajectory: retry_harness creates new trajectory_id per iteration
9. `resolve_legacy_event_type()` returns correct string for all 5 canonical types × all phases

---

## Files Modified

| Step | File |
|------|------|
| 1-4, 10-11 | `logging_core.py` |
| 5, 7 | `execution.py` |
| 6 | `runner.py` |
| 8 | `execution_v2.py` |
| 9 | `retry_harness.py` |
