# Plan: Canonical Event Schema v2 — Single Emission Point

## Context

The logging system passes `RunLogger` explicitly through the call stack (no global state). However, schema knowledge leaks outside `logging_core`: `_build_metrics_payload()` in `execution.py` constructs a 22+ field dict, `log_call()` builds its own record, and `log_run()` builds a third. Three construction paths, no schema validation, no causal chaining, no structured sections.

This plan introduces `RunLogger.emit_event()` as the **single canonical emission point**. Every event conforms to a structured schema. **Zero schema logic exists outside `logging_core`.**

---

## 1. Current State Analysis

### Logging paths (all in logging_core.RunLogger)

| Method | Output | Problem |
|--------|--------|---------|
| `log_call()` | calls/*.json + calls_flat/*.txt + events.jsonl | Builds 15-field record internally |
| `log_run()` | run.jsonl | Independent 12-field record — second schema |
| `log_event()` | events.jsonl | Opaque `payload` dict — no structure |
| `end_case()` | events.jsonl | Receives pre-built dict from `_build_metrics_payload()` |

### Schema leakage (MUST eliminate)

- **`execution.py:_build_metrics_payload()`**: 22+ field dict with V2-conditional fields. Called by 6 functions.
- **`logging_core.py:log_call()`**: Builds its own call record format.
- **`logging_core.py:log_run()`**: Third independent record format.

### aggregate.py backward compatibility (CRITICAL)

Reads events.jsonl keying on:
- `e["event_type"]` — exact strings: `"case.end"`, `"case.failed"`, `"call.generate"`, `"call.classify"`, `"parse.result"`
- `e.get("model")`, `e.get("condition")`, `e.get("trace_id")`, `e.get("case_id")`
- `e.get("payload", {})` — reads `payload.get("pass")`, `payload.get("score")`, `payload.get("latency_ms")`, etc.

---

## 2. Target Architecture

### Single emission function

**`RunLogger.emit_event(event_type, *, ...keyword_args) -> int`**

Responsibilities:
1. Construct full canonical schema from keyword args + internal state
2. Assign `event_id`, `timestamp`, `event_index_within_trace`
3. Validate all 14 sections present
4. Build backward-compat envelope (old flat keys) for aggregate.py
5. Write to events.jsonl
6. Return `event_id` for causal chaining

**Invariant:** `emit_event()` is the ONLY function that calls `_write_event()`.

### Canonical schema (v2 — all 7 issues fixed)

```json
{
  "schema_version": "1.0",
  "event_id": "int (monotonic per-instance)",
  "event_type": "llm_call | execution_eval | reasoning_eval | pipeline_state | error",
  "timestamp": "ISO-8601",

  "run": {
    "run_id": "string",
    "experiment_name": "string",
    "trial": 0,
    "model": "string"
  },

  "trace": {
    "trace_id": "uuid-hex",
    "parent_event_id": "int|null",
    "trajectory_id": "string|null",
    "event_index_within_trace": 0
  },

  "context": {
    "case_id": "string",
    "condition": "string",
    "attempt_idx": 0,
    "step": "initial|retry|repair|contract_elicit|contract_code|contract_retry|classify",
    "phase": "generation|classification|evaluation|case|run",
    "node": "string|null",
    "edge": "string|null"
  },

  "prompt": {
    "prompt_family": "string|null",
    "prompt_name": "string|null",
    "prompt_version": "string|null",
    "prompt_hash": "sha256-of-full-prompt-string",
    "template_id": "sha256-of-component-plan",
    "variables_hash": "sha256-of-sorted-variable-keys",
    "tokens_input_estimate": 0
  },

  "llm_call": {
    "call_id": 0,
    "provider": "openai",
    "model": "string",
    "temperature": 0.0,
    "max_tokens": 0,
    "tokens_output_estimate": 0,
    "latency_ms": 0,
    "status": "success|error",
    "error_type": "string|null",
    "request_path": "calls/000001.json",
    "response_path": "calls/000001.json",
    "flat_path": "calls_flat/000001_generation.txt"
  },

  "execution": {
    "ran": true,
    "passed": true,
    "score": 1.0,
    "tests_run": 0,
    "tests_passed": 0,
    "runtime_ms": 0,
    "error": "string|null"
  },

  "reasoning": {
    "evaluated": false,
    "reasoning_correct": "true|false|null",
    "failure_type": "string|null",
    "confidence": "string|null"
  },

  "artifacts": {
    "code_path": "string|null",
    "diff_path": "string|null",
    "stdout_path": "string|null",
    "stderr_path": "string|null"
  },

  "metrics": {
    "cumulative_calls": 0,
    "cumulative_cost": 0.0
  },

  "extra": {}
}
```

All 14 sections ALWAYS present. Inapplicable fields are `null`.

---

## 3. Fixes for All 7 Critical Issues

### Fix 1: Schema Leakage — ZERO schema logic outside logging_core

**Previous (WRONG):** `_extract_condition_extras(ev, condition)` in execution.py decides which fields go in `extra`.

**Corrected:** Execution functions pass `raw_ev=ev` (the entire evaluation dict) to `logger.end_case()`. The RunLogger's `emit_event()` internally calls `_extract_structured_fields(raw_ev, condition)` to:
1. Extract `execution.*` fields from `raw_ev["execution"]`
2. Extract `reasoning.*` fields from `raw_ev`
3. Package remaining condition-specific fields into `extra`

```
# execution.py passes raw data ONLY:
logger.end_case(cid, condition=condition, raw_ev=ev, elapsed_ms=elapsed*1000)

# logging_core.py:emit_event() internally does ALL extraction:
def _extract_from_raw_ev(self, raw_ev: dict, condition: str) -> dict:
    """Extract canonical fields from raw evaluation dict. ONLY called inside emit_event()."""
    # execution section
    exec_data = raw_ev.get("execution", {})
    execution = {
        "ran": exec_data.get("ran"),
        "passed": raw_ev.get("pass"),
        "score": raw_ev.get("score"),
        "tests_run": exec_data.get("total_tests"),
        "tests_passed": exec_data.get("tests_passed"),
        "runtime_ms": None,  # filled by caller via elapsed_ms
        "error": exec_data.get("error"),
    }
    # reasoning section
    reasoning = {
        "evaluated": raw_ev.get("reasoning_correct") is not None,
        "reasoning_correct": raw_ev.get("reasoning_correct"),
        "failure_type": raw_ev.get("failure_type"),
        "confidence": raw_ev.get("confidence"),
    }
    # extra: everything condition-specific
    extra = {}
    V2_EXTRA_KEYS = {"v2_artifact", "v2_category", "legacy_compat_category", ...}
    CGE_EXTRA_KEYS = {"contract", "gate_results", "cge_executed", ...}
    LEG_EXTRA_KEYS = {"leg_valid", "leg_warnings", "leg_fields"}
    OBSERVABILITY_KEYS = {"code_present", "code_source", "case_validity", "parse_tier", ...}
    ALL_EXTRA = V2_EXTRA_KEYS | CGE_EXTRA_KEYS | LEG_EXTRA_KEYS | OBSERVABILITY_KEYS
    for k in ALL_EXTRA:
        if k in raw_ev:
            extra[k] = raw_ev[k]
    return execution, reasoning, extra
```

**The key sets (`V2_EXTRA_KEYS`, etc.) live in `logging_core.py` as module constants.** When new fields are added, they are added in ONE place.

### Fix 2: Prompt Identity — Deterministic and Stable

**Previous (WRONG):** `prompt_name = join(component_names)` — unstable, collision-prone.

**Corrected:**

| Field | Computation | Stability |
|-------|------------|-----------|
| `prompt_family` | `prompt_assembly["condition"]` (e.g. "baseline_v2") | Stable — from config |
| `prompt_name` | `prompt_assembly["plan_hash"]` (sha256 of component plan) | Deterministic — hash of ordered component list |
| `prompt_version` | `prompt_assembly["config_name"]` (e.g. "v2_ablation_nano") | Stable — from config |
| `prompt_hash` | `hashlib.sha256(full_prompt_string.encode()).hexdigest()` | Authoritative identity — hash of FULL rendered prompt |
| `template_id` | `prompt_assembly["final_prompt_hash"]` | Deterministic — hash of final assembled template |
| `variables_hash` | `hashlib.sha256(sorted(prompt_assembly["variables_used"]).encode()).hexdigest()` | Deterministic — hash of sorted variable key list |

**`prompt_hash` is the authoritative identity.** Two prompts with the same `prompt_hash` are identical. `prompt_name` (plan_hash) identifies the template structure. `variables_hash` identifies which variables were injected. Together they form a unique, reproducible prompt fingerprint.

All computation happens inside `emit_event()` from the `prompt_assembly` dict passed by the caller.

### Fix 3: Token Counting — Renamed to `_estimate`

**Choice: Option B — Rename fields to `tokens_input_estimate` and `tokens_output_estimate`.**

**Rationale:** `tiktoken` is an optional dependency (graceful fallback to chars/4). The field name must not promise precision it cannot guarantee. `_estimate_prompt_tokens()` already exists in `execution.py` and uses tiktoken-with-fallback. `emit_event()` will call this function when token estimation is needed, or accept a pre-computed estimate from the caller.

The existing `_estimate_prompt_tokens(prompt, model)` function moves to `logging_core.py` (it's a utility, not schema logic). Callers that already compute tokens (like `run_single`) pass the estimate. `emit_event()` uses it directly.

### Fix 4: Backward Compatibility — Explicit Mapping

**Compatibility event type map (constant in logging_core.py):**

```python
COMPAT_EVENT_TYPE_MAP = {
    # New canonical type → Old legacy type(s)
    "llm_call": {
        "generation": "call.generate",
        "classification": "call.classify",
        "default": "call.other",
    },
    "execution_eval": "case.end",
    "error": "case.failed",
    "pipeline_state": {
        "case_start": "case.start",
        "run_start": "run.start",
        "run_end": "run.end",
        "metric": "metric.record",
        "default": "pipeline_state",
    },
}
```

**Every emitted event includes BOTH:**
```json
{
  "event_type": "llm_call",
  "event_type_legacy": "call.generate",
  "model": "gpt-4.1-nano",
  "condition": "baseline_v2",
  "case_id": "alias_config_a",
  "trace_id": "57f4fc04...",
  "phase": "generation",
  "payload": { "call_id": 1, "latency_ms": 2851, ... },
  "event_id": 3,
  "run": { ... },
  "trace": { ... },
  "context": { ... },
  ...
}
```

`_build_compat_envelope()` inside `emit_event()`:
1. Sets `event_type_legacy` from `COMPAT_EVENT_TYPE_MAP` based on canonical type + phase
2. Copies `model`, `condition`, `case_id`, `trace_id`, `phase`, `trial` to top-level (flat)
3. Builds `payload` dict from canonical sections (e.g. `payload.latency_ms` from `llm_call.latency_ms`)

aggregate.py reads these flat keys unchanged. Zero changes to aggregate.py.

### Fix 5: Causal Chaining — Complete Parent Rules

| Event Type | Parent Event | Rule |
|------------|-------------|------|
| `pipeline_state` (case.start) | `null` | Root of trace. No parent. |
| `llm_call` (generation, attempt 0) | Case start event_id | `self._current_case_start_event_id` |
| `llm_call` (generation, attempt N>0) | Previous `execution_eval` event_id | Caller passes `parent_event_id` from prior eval |
| `llm_call` (classification) | Preceding `llm_call` (generation) event_id | Caller passes `parent_event_id` from gen call |
| `execution_eval` (case.end) | Last `llm_call` event_id within trace | Caller passes `parent_event_id` from last call |
| `reasoning_eval` | `execution_eval` event_id | Always follows execution |
| `error` (case.failed) | `self._current_case_start_event_id` | Error terminates from case root |
| `pipeline_state` (run.start) | `null` | Run-level, no parent |
| `pipeline_state` (run.end) | `null` | Run-level, no parent |
| `pipeline_state` (graph node) | Previous node's last event_id | Caller passes from graph state |

**Implementation:** `emit_event()` has a `parent_event_id` parameter. If caller provides it, use it. If caller does not provide it AND a case is active, default to `self._current_case_start_event_id`. If no case active, default to `null`.

**Return value matters:** Every wrapper returns `event_id` so callers can chain:
```python
gen_event_id = logger.log_call(...)  # returns event_id of llm_call event
# ... evaluate ...
logger.end_case(cid, ..., parent_event_id=gen_event_id)
```

### Fix 6: run.jsonl — Option B (Derived, Not Independent)

**Choice: Keep run.jsonl BUT it is derived from canonical events.**

**Justification:** run.jsonl serves a different consumer (post-hoc debugging) with different needs (full parsed dict, raw response metadata, code_length). Eliminating it forces either bloating events.jsonl with 2000-char reasoning snippets or losing debugging capability. Neither is acceptable.

**Corrected architecture:**
- `log_run()` does NOT construct an independent schema
- `log_run()` calls `emit_event("execution_eval", ...)` first (getting the canonical event_id)
- Then appends a debug record to `run.jsonl` that REFERENCES the canonical event_id:

```python
def log_run(self, case_id, condition, model, prompt, raw_output, parsed, ev,
            canonical_event_id: int) -> None:
    record = {
        "canonical_event_id": canonical_event_id,  # cross-reference
        "run_id": self._run_id,
        "trace_id": self._current_trace_id,
        "case_id": case_id,
        ...debug fields...
    }
    # append to run.jsonl
```

**Invariant:** `run.jsonl` is a debug artifact. It REFERENCES canonical events but NEVER defines schema. Deleting `run.jsonl` loses no metrics — everything is in `events.jsonl`.

### Fix 7: Parallel Safety — Per-Instance Isolation

**Current state is already safe:**
- `orchestrate.py` uses `ProcessPoolExecutor` — each worker is a separate OS process
- Each worker creates its own `RunLogger` instance locally (never pickled)
- `_event_counter` and `_call_counter` are instance variables, not globals
- Each worker writes to its own `run_dir/events.jsonl`
- No shared mutable state exists

**Explicit guarantees in the plan:**
1. `RunLogger` has ZERO class-level mutable state — all counters are `self._*`
2. `emit_event()` reads only `self._*` fields — no module-level state
3. `event_id` is unique within one `events.jsonl` file (per-instance monotonic), NOT globally unique. Global uniqueness comes from `(run_id, event_id)` composite key.
4. `trace_id` is a UUID generated per-case — globally unique by construction
5. The `extra` key sets (`V2_EXTRA_KEYS`, etc.) are `frozenset` constants — immutable, safe to read from any process

**Thread safety note:** If threads are introduced in the future, `_event_counter` and `_call_counter` would need `threading.Lock`. Current design uses `self._*` fields that are trivially lockable per-instance. No redesign needed — add lock in `_write_event()`.

---

## 4. New Schema Fields

### `trace.trajectory_id`

**Purpose:** Groups events across retry iterations within a single case execution. `trace_id` identifies one case execution. `trajectory_id` identifies one retry chain (attempt 0 → attempt 1 → attempt 2).

**Computation:** `f"{trace_id}:{attempt_idx}"` — derived in `emit_event()` from `trace_id` + `attempt_idx`. For non-retry conditions, `trajectory_id = trace_id` (single trajectory).

### `trace.event_index_within_trace`

**Purpose:** Provides deterministic ordering within a trace without relying on timestamp parsing.

**Computation:** `self._trace_event_counter` — per-trace monotonic counter, reset on `start_case()`, incremented on every `emit_event()` call where `trace_id` is active.

---

## 5. Field Mapping Table (Complete)

| Field | Class | Source |
|-------|-------|--------|
| `schema_version` | (C) | Constant `"1.0"` |
| `event_id` | (B) | `self._event_counter` (per-instance monotonic) |
| `event_type` | (A) | Caller argument |
| `timestamp` | (B) | `datetime.now().isoformat()` |
| `run.run_id` | (B) | `self._run_id` |
| `run.experiment_name` | (B) | `self._experiment_name` (from constructor) |
| `run.trial` | (B) | `self._trial` |
| `run.model` | (B) | `self._model` |
| `trace.trace_id` | (B) | `self._current_trace_id` |
| `trace.parent_event_id` | (A/B) | Caller or default `self._current_case_start_event_id` |
| `trace.trajectory_id` | (B) | `f"{trace_id}:{attempt_idx}"` computed in emit_event |
| `trace.event_index_within_trace` | (B) | `self._trace_event_counter` |
| `context.case_id` | (A) | Caller |
| `context.condition` | (A/B) | Caller or `self._condition` |
| `context.attempt_idx` | (A) | Caller |
| `context.step` | (A) | Caller |
| `context.phase` | (A/B) | Caller or inferred |
| `context.node` | (A) | Caller (null for non-graph) |
| `context.edge` | (A) | Caller (null for non-graph) |
| `prompt.prompt_family` | (A) | `prompt_assembly["condition"]` |
| `prompt.prompt_name` | (A) | `prompt_assembly["plan_hash"]` |
| `prompt.prompt_version` | (A) | `prompt_assembly["config_name"]` |
| `prompt.prompt_hash` | (B) | `sha256(full_prompt_string)` computed in emit_event |
| `prompt.template_id` | (A) | `prompt_assembly["final_prompt_hash"]` |
| `prompt.variables_hash` | (B) | `sha256(sorted(variables_used))` computed in emit_event |
| `prompt.tokens_input_estimate` | (A) | Caller (from `_estimate_prompt_tokens`) |
| `llm_call.call_id` | (B) | `self._call_counter` |
| `llm_call.provider` | (C) | `"openai"` |
| `llm_call.model` | (A) | Caller |
| `llm_call.temperature` | (C) | From experiment_config |
| `llm_call.max_tokens` | (C) | From experiment_config |
| `llm_call.tokens_output_estimate` | (A) | `_estimate_prompt_tokens(response, model)` |
| `llm_call.latency_ms` | (A) | `round(elapsed_seconds * 1000)` |
| `llm_call.status` | (A) | `"error"` if error else `"success"` |
| `llm_call.error_type` | (A) | Error string or null |
| `llm_call.request_path` | (B) | Computed from call_id |
| `llm_call.response_path` | (B) | Computed from call_id |
| `llm_call.flat_path` | (B) | Computed from call_id + phase |
| `execution.*` | (A) | Extracted from `raw_ev` inside emit_event via `_extract_from_raw_ev()` |
| `reasoning.*` | (A) | Extracted from `raw_ev` inside emit_event via `_extract_from_raw_ev()` |
| `artifacts.*` | (A) | Caller (all null for now) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (null for now) |
| `extra` | (A/B) | Condition-specific fields extracted from `raw_ev` inside emit_event |

---

## 6. Call Site Contracts

**Statement: execution.py, execution_v2.py, runner.py, llm.py, and retry_harness.py MUST NOT construct event dictionaries. They pass raw values only.**

### runner.py
- Creates `RunLogger(run_dir, run_id, model, condition=None, trial, experiment_name=...)`
- `trace_id, case_event_id = logger.start_case(cid)` — captures both
- `logger.emit_event("pipeline_state", ...)` for run.start/run.end
- On exception: `logger.fail_case(cid, error_str, condition=condition)`

### execution.py
- Passes `raw_ev=ev` (the complete evaluation dict) to `logger.end_case()`
- Passes `elapsed_ms`, `condition`, `attempt_idx`, `parent_event_id`
- Does NOT select fields, name fields, or structure extra
- `logger.log_run(...)` for debug records (references canonical event_id)

### llm.py
- `_log_call_if_logger()` passes raw args to `logger.log_call()`
- Does NOT construct any event dict

---

## 7. Migration Plan (Ordered)

### Step 1: Add `emit_event()` + schema constants to RunLogger
**File:** `logging_core.py`
- Add `emit_event()` with full canonical schema construction
- Add `_extract_from_raw_ev()` for extraction from evaluation dicts
- Add `_build_compat_envelope()` for aggregate.py compatibility
- Add `COMPAT_EVENT_TYPE_MAP`, `V2_EXTRA_KEYS`, `CGE_EXTRA_KEYS`, `LEG_EXTRA_KEYS`, `OBSERVABILITY_KEYS`
- Add `experiment_name` to constructor, `_current_case_start_event_id`, `_trace_event_counter`
- Move `_estimate_prompt_tokens()` from execution.py to logging_core.py
- Test: emit_event produces canonical + compat structure

### Step 2: Convert `log_call()` to delegate to `emit_event()`
**File:** `logging_core.py`
- File writes unchanged; event write delegates to `emit_event("llm_call", ...)`
- No caller changes
- Test: events.jsonl compat layer works

### Step 3: Convert case lifecycle methods to delegate to `emit_event()`
**File:** `logging_core.py`
- `end_case(case_id, *, condition, raw_ev, elapsed_ms, parent_event_id, ...)` — new signature
- `start_case()` returns `CaseHandle(trace_id, event_id)` namedtuple
- `fail_case()` delegates to `emit_event("error", ...)`
- Test: case lifecycle correct

### Step 4: Convert `log_event()` and `log_metric()` to delegate
**File:** `logging_core.py`
- Thin wrappers around `emit_event("pipeline_state", ...)`
- Test: run.start/run.end events

### Step 5: Update runner.py
**File:** `runner.py`
- Pass `experiment_name` to constructor
- Handle `CaseHandle` return
- Capture and pass `parent_event_id` from `start_case`
- Test: e2e smoke test

### Step 6: Update execution.py — eliminate `_build_metrics_payload()`
**File:** `execution.py`
- All functions: `logger.end_case(cid, condition=condition, raw_ev=ev, elapsed_ms=..., parent_event_id=gen_event_id)`
- Capture `event_id` from `logger.log_call()` for parent chaining
- Delete `_build_metrics_payload()`
- Delete `_estimate_prompt_tokens()` (moved to logging_core)
- Test: all v1 conditions

### Step 7: Update execution_v2.py
**File:** `execution_v2.py`
- Same pattern as Step 6
- Test: v2 conditions

### Step 8: Update retry_harness.py
**File:** `retry_harness.py`
- Same pattern, pass `attempt_idx` per iteration
- Chain `parent_event_id` through retry loop
- Test: retry conditions

### Step 9: Update `finalize()` and `validate()`
**File:** `logging_core.py`
- Recognize new event types
- Validate canonical schema on finalize
- Test: metrics.json correct

### Step 10: Update `log_run()` to reference canonical events
**File:** `logging_core.py`
- Accept `canonical_event_id` parameter
- Write cross-reference in run.jsonl record
- Test: run.jsonl records have canonical_event_id

---

## 8. Validation + Invariants

### In `emit_event()`
1. `event_type ∈ VALID_CANONICAL_TYPES` (5 types)
2. Trace required: `llm_call`, `execution_eval`, `error` when case active → trace_id non-null
3. Logger not closed → RuntimeError
4. All 14 sections present in output
5. `event_id` strictly monotonic
6. `run_id` non-null

### In `finalize()`
7. Case pairing: every case.start matched by case.end or case.failed
8. Call file 1:1: every `llm_call` event has corresponding files
9. First event is run.start, last is run.end

### Schema enforcement
10. `CANONICAL_SCHEMA_SECTIONS = frozenset({"schema_version", "event_id", "event_type", "timestamp", "run", "trace", "context", "prompt", "llm_call", "execution", "reasoning", "artifacts", "metrics", "extra"})` — checked on every emit

---

## 9. Failure Modes

| Mode | Prevention |
|------|------------|
| Duplicate writes | `emit_event()` is ONLY writer. Wrappers call once. |
| Partial schema | All 14 sections always constructed. No early returns. |
| Mismatched context | All identity from `self._*` or explicit params. No globals. |
| Race conditions | Per-instance counters. No class-level mutable state. Trivially lockable. |
| Schema drift | Extra-field key sets are frozenset constants in logging_core. |
| Compat break | `_build_compat_envelope()` preserves all flat keys aggregate.py reads. |
| Parent chain broken | Default parent = `_current_case_start_event_id`. Explicit override from caller. |

---

## Files Modified

| Step | File |
|------|------|
| 1-4, 9-10 | `logging_core.py` |
| 5 | `runner.py` |
| 6 | `execution.py` |
| 7 | `execution_v2.py` |
| 8 | `retry_harness.py` |

---

## Verification

1. Unit test: `emit_event()` canonical + compat structure for each of 5 event types
2. Smoke test: 3 cases x 3 conditions, aggregate.py produces identical dashboard.json
3. Schema validation: `finalize()` validates every event in events.jsonl
4. Causal chain: parent_event_id forms correct DAG for multi-attempt case
5. Parallel safety: two RunLogger instances in same process, verify independent counters
6. Regression: `_build_metrics_payload` import raises ImportError (deleted)
