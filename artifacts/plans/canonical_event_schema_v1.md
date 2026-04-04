# Plan: Canonical Event Schema — Single Emission Point

## Context

The logging system was refactored (Step 3 of v5) to pass `RunLogger` explicitly through the call stack. This eliminated global logging state. However, **schema knowledge still leaks outside `logging_core`**: `_build_metrics_payload()` in `execution.py` constructs a 22+ field dict, `log_call()` builds its own record dict, and `log_run()` builds a third. There are three separate record construction paths, no schema validation beyond event_type membership, no causal chaining between events, and no structured sections — just flat `payload` dicts.

This plan introduces `RunLogger.emit_event()` as the **single canonical emission point** for all events. Every event conforms to a structured schema. No module outside `logging_core` constructs event dictionaries.

---

## 1. Current State Analysis

### Current logging paths (all in logging_core.RunLogger)

| Path | Method | Output | Record construction |
|------|--------|--------|---------------------|
| LLM calls | `log_call()` | calls/*.json + calls_flat/*.txt + events.jsonl | Builds 15-field record internally |
| Case detail | `log_run()` | run.jsonl | Builds 12-field record internally |
| Events | `log_event()` | events.jsonl | 10-field envelope + opaque `payload` dict |
| Case lifecycle | `start_case/end_case/fail_case` | events.jsonl | Delegate to `log_event()` |
| Metrics | `log_metric()` | events.jsonl | Delegate to `log_event()` |

### Schema knowledge leakage

- **`execution.py:_build_metrics_payload()`** (line 144): constructs 22+ field payload dict with V2-conditional fields. Called by `run_single`, `run_repair_loop`, `run_contract_gated`, `run_leg_reduction`, `run_v2`, `run_retry_harness`.
- **`llm.py:_log_call_if_logger()`** (line 108): passes raw args to `logger.log_call()` — clean, but `log_call()` internally constructs its own record format.
- **`logging_core.py:log_run()`** (line 457): third independent record format for run.jsonl.

### Inconsistencies

1. `log_call` events have `payload.latency_ms` but case.end events have `payload.elapsed_seconds` — different units for the same concept.
2. `case.end` payload has 22+ flat fields; `call.generate` payload has 5 fields — wildly different structures.
3. No `parent_event_id` — cannot trace causal chains (which LLM call produced which evaluation).
4. No `schema_version` — cannot distinguish event formats across runs.

### aggregate.py backward compatibility (CRITICAL)

`aggregate.py` reads events.jsonl and keys on:
- `e["event_type"]` — exact strings: `"case.end"`, `"case.failed"`, `"call.generate"`, `"call.classify"`, `"parse.result"`
- `e.get("model")`, `e.get("condition")`, `e.get("trace_id")`, `e.get("case_id")`
- `e.get("payload", {})` — reads `payload.get("pass")`, `payload.get("score")`, `payload.get("latency_ms")`, `payload.get("failure_type")`, `payload.get("error")`, `payload.get("call_id")`

These MUST remain accessible during migration.

---

## 2. Target Architecture

### Single emission function

**Name:** `RunLogger.emit_event(event_type, *, ...keyword_args) -> int`

**Responsibilities:**
1. Construct full canonical schema object from keyword args + internal state
2. Assign `event_id` (monotonic), `timestamp`
3. Validate: all sections present, required fields non-null based on event_type
4. Write backward-compat envelope (old flat keys at top level) + canonical record to events.jsonl
5. Return `event_id` for causal chaining

**Invariant:** `emit_event()` is the ONLY function that calls `_write_event()`. All other methods (`log_call`, `end_case`, `start_case`, `fail_case`, `log_metric`, `log_event`) are thin wrappers that call `emit_event()`.

### Canonical schema

```json
{
  "schema_version": "1.0",
  "event_id": "int (monotonic)",
  "event_type": "llm_call | execution_eval | reasoning_eval | pipeline_state | error",
  "timestamp": "ISO-8601",
  "run":       { "run_id", "experiment_name", "trial", "model" },
  "trace":     { "trace_id", "parent_event_id" },
  "context":   { "case_id", "condition", "attempt_idx", "step", "phase", "node", "edge" },
  "prompt":    { "prompt_family", "prompt_name", "prompt_version", "prompt_hash", "template_id", "variables_hash", "tokens_input" },
  "llm_call":  { "call_id", "provider", "model", "temperature", "max_tokens", "tokens_output", "latency_ms", "status", "error_type", "request_path", "response_path", "flat_path" },
  "execution": { "ran", "passed", "score", "tests_run", "tests_passed", "runtime_ms", "error" },
  "reasoning": { "evaluated", "reasoning_correct", "failure_type", "confidence" },
  "artifacts": { "code_path", "diff_path", "stdout_path", "stderr_path" },
  "metrics":   { "cumulative_calls", "cumulative_cost" },
  "extra":     { "...condition-specific fields..." }
}
```

All sections ALWAYS present. Inapplicable fields are `null`.

---

## 3. Field Mapping

### Classification: (A) passed from caller, (B) computed in RunLogger, (C) constant/config

| Field | Classification | Source |
|-------|---------------|--------|
| `schema_version` | (C) | Constant `"1.0"` |
| `event_id` | (B) | `self._event_counter` |
| `event_type` | (A) | Caller argument |
| `timestamp` | (B) | `datetime.now().isoformat()` |
| `run.run_id` | (B) | `self._run_id` |
| `run.experiment_name` | (B) | `self._experiment_name` (set at construction) |
| `run.trial` | (B) | `self._trial` |
| `run.model` | (B) | `self._model` |
| `trace.trace_id` | (B) | `self._current_trace_id` |
| `trace.parent_event_id` | (A/B) | Caller or `self._current_case_start_event_id` |
| `context.case_id` | (A) | Caller |
| `context.condition` | (A/B) | Caller override or `self._condition` |
| `context.attempt_idx` | (A) | Caller (from `ev["num_attempts"]`) |
| `context.step` | (A) | Caller (e.g. `"elicit"`, `"code"`, `"retry"` for CGE) |
| `context.phase` | (A/B) | Caller or inferred from event_type |
| `context.node` | (A) | Caller (graph_runner `StageSpec.name`) |
| `context.edge` | (A) | Caller (graph_runner transition) |
| `prompt.prompt_hash` | (A) | From `prompt_assembly["final_prompt_hash"]` |
| `prompt.template_id` | (A) | From `prompt_assembly["plan_hash"]` |
| `prompt.prompt_name` | (A) | From `prompt_assembly["component_names"]` joined |
| `prompt.prompt_family` | (A) | From `prompt_assembly["condition"]` |
| `prompt.prompt_version` | (A) | From `prompt_assembly["config_name"]` |
| `prompt.variables_hash` | (A) | Hash of variables_used list |
| `prompt.tokens_input` | (A) | Caller (`len(prompt)`) |
| `llm_call.call_id` | (B) | `self._call_counter` |
| `llm_call.provider` | (C) | `"openai"` (from config) |
| `llm_call.model` | (A) | Caller |
| `llm_call.temperature` | (C) | From `experiment_config` model spec |
| `llm_call.max_tokens` | (C) | From `experiment_config` model spec |
| `llm_call.tokens_output` | (A) | `len(response)` |
| `llm_call.latency_ms` | (A) | `round(elapsed_seconds * 1000)` |
| `llm_call.status` | (A) | `"error"` if error else `"success"` |
| `llm_call.error_type` | (A) | Error string or `null` |
| `llm_call.request_path` | (B) | `f"calls/{call_id:06d}.json"` |
| `llm_call.response_path` | (B) | Same (prompt+response in one file) |
| `llm_call.flat_path` | (B) | `f"calls_flat/{call_id:06d}_{phase}.txt"` |
| `execution.ran` | (A) | `ev["execution"]["ran"]` |
| `execution.passed` | (A) | `ev["pass"]` |
| `execution.score` | (A) | `ev["score"]` |
| `execution.tests_run` | (A) | `ev["execution"].get("total_tests")` |
| `execution.tests_passed` | (A) | `ev["execution"].get("tests_passed")` |
| `execution.runtime_ms` | (A) | Caller (elapsed_seconds * 1000) |
| `execution.error` | (A) | `ev["execution"].get("error")` |
| `reasoning.evaluated` | (A) | `ev["reasoning_correct"] is not None` |
| `reasoning.reasoning_correct` | (A) | `ev["reasoning_correct"]` |
| `reasoning.failure_type` | (A) | `ev["failure_type"]` |
| `reasoning.confidence` | (A) | `ev["confidence"]` |
| `artifacts.*` | (A) | Caller (`null` for now — future artifact paths) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (`null` for now — future cost tracking) |
| `extra` | (A) | Condition-specific fields (v2_artifact, gate_results, leg_fields, etc.) |

---

## 4. Call Site Contracts

**Statement: execution.py, execution_v2.py, runner.py, llm.py, and retry_harness.py MUST NOT construct event dictionaries. They pass raw values only.**

### runner.py

- Creates `RunLogger` with `experiment_name` from config
- Calls `logger.start_case(cid)` → receives `(trace_id, case_start_event_id)`
- Calls `logger.emit_event("pipeline_state", ...)` for run.start/run.end
- On exception: calls `logger.fail_case(cid, error_str, condition=condition)`

### execution.py (run_single, run_repair_loop, run_contract_gated, run_leg_reduction)

- Calls `logger.end_case(cid, condition=condition, ran=..., passed=..., score=..., ...)` with named keyword args extracted from `ev` dict
- Calls `logger.log_run(...)` for detailed run.jsonl record (unchanged)
- Packages condition-specific data via `_extract_condition_extras(ev, condition) -> dict` — selects fields for `extra`, NOT schema construction

### llm.py

- `_log_call_if_logger()` calls `logger.log_call(model, prompt, response, elapsed, case_id, phase, condition, error, prompt_assembly)` — unchanged interface

### execution_v2.py / retry_harness.py

- Same contract as execution.py

---

## 5. Migration Plan (Ordered)

Each step preserves system functionality. Tests verify no regression.

### Step 1: Add `emit_event()` to RunLogger
**File:** `logging_core.py`
- Add `emit_event()` method with canonical schema construction
- Add backward-compat envelope writer (`_build_compat_envelope()`) that preserves old top-level keys (`event_type`, `model`, `condition`, `payload`, etc.) for aggregate.py
- Add `experiment_name` parameter to `RunLogger.__init__()`
- Add `_current_case_start_event_id` tracking to `start_case()`
- Add new event types to `VALID_EVENT_TYPES`
- Unit test: `emit_event()` produces both canonical sections AND compat flat keys

### Step 2: Convert `log_call()` to delegate to `emit_event()`
**File:** `logging_core.py`
- `log_call()` still writes calls/*.json and calls_flat/*.txt directly
- Events.jsonl write delegated to `self.emit_event("llm_call", ...)`
- No caller changes
- Test: verify events.jsonl contains both canonical `llm_call` section AND compat `payload.latency_ms`

### Step 3: Convert `start_case/end_case/fail_case` to delegate to `emit_event()`
**File:** `logging_core.py`
- `end_case()` signature changes from `(case_id, payload_dict)` to `(case_id, *, ran, passed, score, ..., extra)`
- `start_case()` returns `CaseHandle(trace_id, event_id)` namedtuple (position [0] is `trace_id` for backward compat)
- Test: verify case lifecycle events correct

### Step 4: Convert `log_event()` and `log_metric()` to delegate to `emit_event()`
**File:** `logging_core.py`
- `log_event()` becomes thin wrapper
- Test: run.start/run.end events correct

### Step 5: Update runner.py
**File:** `runner.py`
- Pass `experiment_name` to `RunLogger()` constructor
- Handle `CaseHandle` return from `start_case()`
- Convert `log_event("run.start", {...})` to `emit_event("pipeline_state", ...)`
- Test: end-to-end smoke test (3 cases x 3 conditions)

### Step 6: Update execution.py — eliminate `_build_metrics_payload()`
**File:** `execution.py`
- `run_single`, `run_repair_loop`, `run_contract_gated`, `run_leg_reduction` call `logger.end_case()` with keyword args instead of `_build_metrics_payload()` dict
- Add `_extract_condition_extras(ev, condition) -> dict` helper
- Delete `_build_metrics_payload()`
- Test: verify events match for all v1 conditions

### Step 7: Update execution_v2.py
**File:** `execution_v2.py`
- Same pattern as Step 6
- Remove import of `_build_metrics_payload`
- Test: verify v2 conditions

### Step 8: Update retry_harness.py
**File:** `retry_harness.py`
- Same pattern as Step 6
- Pass `attempt_idx` per iteration
- Test: verify retry conditions

### Step 9: Update `finalize()` and `validate()`
**File:** `logging_core.py`
- Recognize new event types for case lifecycle validation
- Validate canonical schema structure on finalize
- Test: verify finalize produces correct metrics.json

---

## 6. Validation + Invariants

### Assertions in `emit_event()`

1. **event_type** ∈ `{"llm_call", "execution_eval", "reasoning_eval", "pipeline_state", "error"}` (plus legacy during compat)
2. **trace_id required**: if event_type ∈ `{"llm_call", "execution_eval", "error"}` and case active → `trace_id` must be non-null
3. **logger not closed**: `self._closed` → raise `RuntimeError`
4. **All sections present**: every emitted record has all 12 top-level keys
5. **event_id monotonic**: strictly increasing per events.jsonl
6. **run_id non-null**: always present from construction

### Assertions in `finalize()`

7. **Case pairing**: every case.start has exactly one case.end or case.failed
8. **Call file 1:1**: every `llm_call` event's `llm_call.call_id` has corresponding files
9. **First/last event**: first is run.start, last is run.end

---

## 7. Failure Modes to Prevent

| Failure Mode | Prevention |
|---|---|
| **Duplicate event writes** | `emit_event()` is the ONLY writer. Wrappers call it once. |
| **Partial schema emission** | `emit_event()` always constructs ALL 12 sections. No early returns. |
| **Mismatched context** | `condition`, `case_id` from explicit params. `run_id`, `trace_id` from `self._*`. No globals. |
| **Race conditions** | Serial execution only. `_event_counter` local to one RunLogger. No threads. |
| **Schema drift** | `CANONICAL_SCHEMA_SECTIONS` constant defines required sections. Validated in `emit_event()`. |
| **Backward compat break** | Compat envelope preserves old keys at top level. aggregate.py reads these unchanged. |

---

## 8. Architectural Justification

### Why schema construction MUST be centralized

Schema knowledge in multiple files means: adding a field requires touching N files (guaranteed inconsistency), no single validation point (events silently diverge), different callers produce structurally different events for the same event_type (aggregate.py breaks).

With `emit_event()` as the single point: add a field in one place, validated once, emitted uniformly.

### Why call-site assembly is incorrect

`_build_metrics_payload()` in `execution.py` is schema construction disguised as data extraction. It decides which fields exist, their names, their defaults, and their structure. When V2 conditions added 18 extra keys, they were added in execution.py — not where the schema lives.

### How this supports GraphRunner DAG execution

The canonical schema has `context.node` and `context.edge` fields. When the graph_runner executes a stage, it emits a `pipeline_state` event with `node=stage.name` and `edge=prev→current`. The `trace.parent_event_id` links each stage's events to the previous stage's output event, forming a DAG-aware causal chain reconstructible from events.jsonl alone.

### How trace_id + parent_event_id enable causal tracing

- `trace_id` groups all events for one case execution (flat grouping)
- `parent_event_id` chains events causally (directed graph)

Together: "Show me everything for this case" → filter by `trace_id`. "What caused this failure?" → walk `parent_event_id` backward.

---

## Verification

1. **Unit tests**: `emit_event()` produces correct canonical + compat structure for each event type
2. **Smoke test**: 3 cases x 3 conditions, verify events.jsonl has all sections, aggregate.py still works
3. **Backward compat**: run aggregate.py on new events.jsonl — same dashboard.json output
4. **Schema validation**: `finalize()` validates every event against canonical schema
5. **Causal chain**: verify `parent_event_id` links form correct chain for a multi-attempt case
