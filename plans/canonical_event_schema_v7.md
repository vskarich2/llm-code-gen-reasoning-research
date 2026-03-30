# Plan: Canonical Event Schema v7 — Locked

## Context

The logging system passes `RunLogger` explicitly through the call stack. Schema knowledge leaks outside `logging_core`: `_build_metrics_payload()` in `execution.py` constructs event dicts, `log_call()` and `log_run()` each build independent record formats. This plan introduces `RunLogger.emit_event()` as the single canonical emission point.

---

## 1. Event Type Semantics — Global Definition

**Choice: Option B — backward compatibility priority.**

This is a backward compatibility concession. `aggregate.py` keys on `e["event_type"] == "case.end"`. The canonical type is authoritative in code (the first argument to `emit_event()`). The legacy type occupies the `event_type` key in the JSON record.

| JSON field | Role | Example | Who sets it |
|---|---|---|---|
| `event_type` | Legacy value. Read by aggregate.py. | `"case.end"` | `resolve_legacy_event_type()` inside `emit_event()` |
| `event_type_canonical` | Canonical value. Authoritative classification. | `"execution_eval"` | First argument to `emit_event()` |

These two fields always have different values. This definition applies to every section of this document.

---

## 2. Phase — Closed Enum

`phase` is constrained to a closed set. Any value outside this set raises `RuntimeError` inside `emit_event()` before any write.

```python
VALID_PHASES = frozenset({
    "generation",
    "classification",
    "evaluation",
    "case",
    "pipeline",
})
```

Enforcement in `emit_event()`:

```python
if phase is not None and phase not in VALID_PHASES:
    raise RuntimeError(
        f"Invalid phase: {phase!r}. Must be one of {sorted(VALID_PHASES)}."
    )
```

`resolve_legacy_event_type()` receives only validated `phase` values. It cannot silently degrade due to invalid input.

---

## 3. Architecture

### Single emission function

`RunLogger.emit_event(event_type_canonical, *, ...keyword_args) -> int` is the ONLY function that writes to events.jsonl.

Steps in order:

1. Validate `event_type_canonical` ∈ `{"llm_call", "execution_eval", "reasoning_eval", "pipeline_state", "error"}`
2. Validate `phase` ∈ `VALID_PHASES` (if provided)
3. Enforce `PARENT_REQUIRED` constraint
4. If `raw_ev` is provided: call `_build_canonical_and_extra(raw_ev, runtime_ms)` → receive `(execution_section, reasoning_section, extra_section, consumed_keys)`
5. Run overlap invariant check
6. Assemble the full record: insert returned sections directly — `emit_event()` does NOT read `raw_ev`
7. Compute `event_type` via `resolve_legacy_event_type(event_type_canonical, phase, step)`
8. Build compat envelope
9. Assign `event_id`, `timestamp`, `event_index_within_trace`
10. Write to events.jsonl
11. Return `event_id`

### Canonical schema (as written to events.jsonl)

```json
{
  "schema_version": "1.0",
  "event_id": "int",
  "event_type": "case.end | call.generate | ...",
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

Plus flat legacy keys at top level: `model`, `condition`, `case_id`, `trace_id`, `trial`, `phase`, `payload`.

All 14 canonical sections are ALWAYS present. Inapplicable fields are `null`.

---

## 4. Schema Definition Boundaries

Field membership and schema structure are orthogonal responsibilities defined in separate functions.

**Field membership**: Defined by `_build_canonical_and_extra()`. This function determines which `raw_ev` fields belong to the `execution` section, which belong to the `reasoning` section, and which go to `extra`.

**Schema structure**: Defined by `emit_event()`. This function determines the 14-section layout, where extracted sections are placed, and the compat envelope. `emit_event()` does not decide which `raw_ev` fields are canonical — it delegates to `_build_canonical_and_extra()` and inserts returned dicts by reference.

Field membership is defined exclusively by `_build_canonical_and_extra()`. Schema structure (section layout) is defined by `emit_event()`. These responsibilities are orthogonal and do not overlap.

---

## 5. Extraction — Field Membership Definition

### `consumed_keys` semantics

`consumed_keys` tracks ONLY top-level keys of `raw_ev`. It does not track nested keys within those top-level values.

### Atomic source invariant

A canonical field originates from exactly one top-level key in `raw_ev`. Nested structures are fully encapsulated under their top-level key. No canonical field is constructed by merging values from multiple top-level keys. Cross-key merging is forbidden.

Concretely:
- `execution.ran` comes from `raw_ev["execution"]["ran"]` — one top-level key: `"execution"`
- `execution.passed` comes from `raw_ev["pass"]` — one top-level key: `"pass"`
- `reasoning.failure_type` comes from `raw_ev["failure_type"]` — one top-level key: `"failure_type"`

No field reads from both `raw_ev["execution"]` and `raw_ev["reasoning_correct"]` to produce a single value.

This invariant is enforced by design: `_build_canonical_and_extra()` is structured so each canonical field assignment reads from exactly one `raw_ev[key]` or `raw_ev[key][subkey]` access. Code review enforces this. If a future developer writes `some_field = raw_ev["a"] + raw_ev["b"]`, it violates the single-source invariant and must be rejected.

### Implementation

```python
def _build_canonical_and_extra(
    self, raw_ev: dict, runtime_ms: float | None
) -> tuple[dict, dict, dict, set]:
    """Extract canonical sections from raw_ev.

    Returns (execution_section, reasoning_section, extra_section, consumed_keys).

    consumed_keys: set of top-level raw_ev keys that were read.
    extra_section: all top-level keys NOT in consumed_keys, with their values.

    Invariants enforced by this function's structure:
    - consumed_keys tracks ONLY top-level keys
    - Each canonical field reads from exactly one top-level key
    - extra = {k: v for k, v in raw_ev.items() if k not in consumed_keys}
    """
    consumed_keys: set[str] = set()

    # --- execution section ---
    # Source top-level keys: "execution", "pass", "score"
    exec_data = raw_ev.get("execution", {})
    consumed_keys.add("execution")
    execution_section = {
        "ran": exec_data.get("ran"),              # from "execution"
        "passed": raw_ev.get("pass"),             # from "pass"
        "score": raw_ev.get("score"),             # from "score"
        "tests_run": exec_data.get("total_tests"),  # from "execution"
        "tests_passed": exec_data.get("tests_passed"),  # from "execution"
        "runtime_ms": runtime_ms,                 # from caller parameter
        "error": exec_data.get("error"),          # from "execution"
    }
    consumed_keys.update({"pass", "score"})

    # --- reasoning section ---
    # Source top-level keys: "reasoning_correct", "failure_type", "confidence"
    reasoning_section = {
        "evaluated": raw_ev.get("reasoning_correct") is not None,  # from "reasoning_correct"
        "reasoning_correct": raw_ev.get("reasoning_correct"),       # from "reasoning_correct"
        "failure_type": raw_ev.get("failure_type"),                 # from "failure_type"
        "confidence": raw_ev.get("confidence"),                     # from "confidence"
    }
    consumed_keys.update({"reasoning_correct", "failure_type", "confidence"})

    # --- keys consumed for context (read by emit_event for context/compat, not stored in execution/reasoning) ---
    consumed_keys.update({"condition", "operator_used", "num_attempts", "alignment"})

    # --- extra: every top-level key NOT consumed ---
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

## 6. Runtime Invariants

### Invariant 1: No overlap between canonical and extra

```python
def _enforce_no_overlap(self, consumed_keys: set, extra_section: dict):
    overlap = consumed_keys & set(extra_section.keys())
    if overlap:
        raise RuntimeError(
            f"SCHEMA INVARIANT VIOLATION: top-level keys {overlap} appear in both "
            f"consumed_keys and extra_section. Fix _build_canonical_and_extra()."
        )
```

Runs inside `emit_event()` after extraction, before any write.

### Invariant 2: Atomic source (design-enforced)

Each canonical field assignment in `_build_canonical_and_extra()` reads from exactly one top-level `raw_ev` key. This is enforced by code structure and review, not by runtime check, because it is a property of the extraction code itself, not of the data. The inline source comments (`# from "execution"`, `# from "pass"`, etc.) make violations immediately visible during review.

### Invariant 3: Phase validation

```python
if phase is not None and phase not in VALID_PHASES:
    raise RuntimeError(f"Invalid phase: {phase!r}.")
```

Runs inside `emit_event()` before any write.

### Invariant 4: Parent enforcement

```python
PARENT_REQUIRED = frozenset({"llm_call", "execution_eval", "reasoning_eval", "error"})

if event_type_canonical in PARENT_REQUIRED and parent_event_id is None:
    raise RuntimeError(f"parent_event_id required for {event_type_canonical!r}.")
```

Runs inside `emit_event()` before any write.

---

## 7. Formal Trajectory Definition

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

## 8. Parent Event ID

```python
PARENT_REQUIRED = frozenset({"llm_call", "execution_eval", "reasoning_eval", "error"})
```

Missing parent for these types raises `RuntimeError`. `pipeline_state`: parent is `null`, not enforced.

| Path | Event (canonical) | parent_event_id |
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

## 9. Prompt Identity — Computed by Caller

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

## 10. Token Estimate Semantics

`tokens_input_estimate` and `tokens_output_estimate` are integer estimates of token count. They are not exact.

Both use `_estimate_prompt_tokens(text, model)` in execution.py:
- With `tiktoken`: exact BPE token count for the model's tokenizer (falls back to `cl100k_base` if model unknown).
- Without `tiktoken`: `len(text) // 4`.

Same function for input and output: both are strings tokenized identically. Callers compute and pass estimates. logging_core stores verbatim.

---

## 11. Compatibility Mapping

### Determinism guarantee

`resolve_legacy_event_type()` is a pure function of three arguments: `(event_type_canonical, phase, step)`. `phase` is guaranteed valid by the `VALID_PHASES` check in `emit_event()` (Section 6, Invariant 3). Invalid phase values never reach this function.

### Implementation

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

### Compat envelope

Every event includes flat legacy keys at top level:

```python
{
    "event_type": resolve_legacy_event_type(event_type_canonical, phase, step),
    "event_type_canonical": event_type_canonical,
    "model": self._model,
    "condition": effective_condition,
    "case_id": case_id,
    "trace_id": self._current_trace_id,
    "trial": self._trial,
    "phase": phase,
    "event_id": event_id,
    "payload": _build_compat_payload(record),
    "schema_version": "1.0",
    ...14 canonical sections...
}
```

### `_build_compat_payload(record) -> dict`

- `llm_call` → `{"call_id": ..., "latency_ms": ..., "prompt_length": ..., "response_length": ..., "error": ...}`
- `execution_eval` → `{"pass": ..., "score": ..., "failure_type": ..., **extra}`
- `error` → `{"error": ...}`
- `pipeline_state` → `{}`

---

## 12. run.jsonl Contract

### Allowed fields (exhaustive)

`canonical_event_id`, `run_id`, `trace_id`, `case_id`, `condition`, `timestamp`, `prompt_length`, `raw_response_length`, `parsed_reasoning` (2000 char max), `parsed_code_length`, `parse_error`, `response_format`, `data_lineage`.

### Forbidden

Any field from canonical `execution`, `reasoning`, `prompt`, `llm_call`, `metrics`, or `artifacts` sections.

### `log_run()` signature

```python
def log_run(self, case_id: str, condition: str, prompt: str,
            raw_output: str, parsed: dict, canonical_event_id: int) -> None:
```

Does not accept `ev`. Writes only allowed fields.

---

## 13. Field Mapping Table

(A) = caller, (B) = RunLogger internal, (C) = constant/config

| Field | Class | Source |
|---|---|---|
| `schema_version` | (C) | `"1.0"` |
| `event_id` | (B) | `self._event_counter` |
| `event_type` | (B) | `resolve_legacy_event_type()` — legacy value |
| `event_type_canonical` | (A) | First arg to `emit_event()` — canonical value |
| `timestamp` | (B) | `datetime.now().isoformat()` |
| `run.*` | (B) | `self._run_id`, `self._experiment_name`, `self._trial`, `self._model` |
| `trace.trace_id` | (B) | `self._current_trace_id` |
| `trace.parent_event_id` | (A) | Caller (REQUIRED for llm_call/execution_eval/reasoning_eval/error) |
| `trace.trajectory_id` | (B) | `self._current_trajectory_id` |
| `trace.event_index_within_trace` | (B) | `self._trace_event_counter` |
| `context.case_id` | (A) | Caller |
| `context.condition` | (A/B) | Caller or `self._condition` |
| `context.attempt_idx` | (A) | Caller |
| `context.step` | (A) | Caller |
| `context.phase` | (A) | Caller (validated against `VALID_PHASES`) |
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
| `execution.*` | (B) | Returned by `_build_canonical_and_extra()`, inserted by reference |
| `reasoning.*` | (B) | Returned by `_build_canonical_and_extra()`, inserted by reference |
| `artifacts.*` | (A) | Caller (all null currently) |
| `metrics.cumulative_calls` | (B) | `self._call_counter` |
| `metrics.cumulative_cost` | (A) | Caller (null currently) |
| `extra` | (B) | Returned by `_build_canonical_and_extra()`, inserted by reference |

---

## 14. Call Site Contracts

execution.py, execution_v2.py, runner.py, llm.py, retry_harness.py MUST NOT construct event dictionaries.

### runner.py
- `RunLogger(run_dir, run_id, model, condition=None, trial, experiment_name=...)`
- `handle = logger.start_case(cid)` → `CaseHandle(trace_id, event_id)`
- Passes `handle.event_id` as `case_start_eid`
- `logger.fail_case(cid, error_str, condition=condition, parent_event_id=handle.event_id)`

### execution.py
- `gen_eid = logger.log_call(...)` — captures event_id
- `end_eid = logger.end_case(cid, condition=condition, raw_ev=ev, runtime_ms=..., parent_event_id=gen_eid)`
- `logger.log_run(cid, condition, prompt, raw_output, parsed, canonical_event_id=end_eid)`
- Does NOT call `_build_metrics_payload()` — deleted

### llm.py
- `_log_call_if_logger()` passes raw args + `parent_event_id` to `logger.log_call()`

---

## 15. Migration Plan

### Step 1: `emit_event()` + extraction + invariants in logging_core.py
- Add `emit_event(event_type_canonical, *, ...)` per Section 3
- Add `_build_canonical_and_extra()` per Section 5
- Add `_enforce_no_overlap()` per Section 6
- Add `VALID_PHASES` enum and validation per Section 2
- Add `resolve_legacy_event_type()` per Section 11
- Add `_build_compat_payload()`, compat envelope
- Add `PARENT_REQUIRED` enforcement
- Add `experiment_name` to constructor
- Add `_current_trajectory_id`, `_trace_event_counter`, `new_trajectory()`
- `start_case()` returns `CaseHandle(trace_id, event_id)`
- Test: canonical + compat output, parent enforcement, overlap invariant, phase validation

### Step 2: Convert `log_call()` → `emit_event("llm_call", ...)`
- File writes unchanged. Event write delegates to `emit_event()`
- `log_call()` requires `parent_event_id`
- Test: events.jsonl compat correct

### Step 3: Convert case lifecycle → `emit_event()`
- `end_case(case_id, *, condition, raw_ev, runtime_ms, parent_event_id)`
- `fail_case(case_id, error, *, condition, parent_event_id)`
- Test: lifecycle events correct

### Step 4: Convert `log_event()` / `log_metric()` → `emit_event("pipeline_state", ...)`
- Test: run.start/run.end correct

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
- Call `new_trajectory()` at trajectory boundaries
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

## 16. Verification

1. `emit_event()` canonical + compat output for all 5 canonical event types
2. Smoke test: 3 cases × 3 conditions, aggregate.py produces identical dashboard.json
3. `finalize()` validates every event structurally
4. Parent chain: CGE elicit→code→retry→eval forms correct DAG
5. Parent enforcement: missing parent on `llm_call` raises RuntimeError
6. Overlap invariant: consumed key appearing in extra raises RuntimeError
7. Phase validation: invalid phase raises RuntimeError
8. Inverse mapping: new field added to `ev` automatically appears in `extra`
9. run.jsonl: zero forbidden canonical fields
10. Trajectory: `run_repair_loop` creates 2; `run_contract_gated` with retry creates 2; with fallback creates 2; `run_retry_harness` creates N
11. `resolve_legacy_event_type()` correct for all canonical type × phase × step
12. `variables_hash` differs for same keys with different values
13. `event_type` in JSON is legacy; `event_type_canonical` is canonical — in all events
14. No static canonical field whitelist exists (grep verification)
15. `emit_event()` does not read `raw_ev` — only `_build_canonical_and_extra()` does

---

## 17. Final Consistency Verification

The following properties hold across all sections of this document:

1. **`consumed_keys` behavior is fully defined**: tracks only top-level keys of `raw_ev` (Section 5). Nested field access occurs strictly under consumed top-level keys. This is explicit in the extraction code and inline comments.

2. **Nested field assumptions are explicit**: each canonical field assignment is annotated with its source top-level key. The atomic source invariant (Section 6, Invariant 2) states each canonical field reads from exactly one top-level key. Cross-key merging is forbidden.

3. **`phase` is fully constrained**: closed enum `VALID_PHASES` (Section 2). Validated in `emit_event()` before any write (Section 6, Invariant 3). Invalid values raise `RuntimeError`.

4. **Compatibility mapping is deterministic**: `resolve_legacy_event_type()` is a pure function of `(event_type_canonical, phase, step)` (Section 11). `phase` is guaranteed valid by prior validation. The function returns a string for every input.

5. **Schema boundaries are precisely defined**: field membership defined exclusively by `_build_canonical_and_extra()`. Schema structure defined by `emit_event()`. These are orthogonal and do not overlap (Section 4).

6. **No ambiguity remains**: every invariant has an enforcement mechanism (runtime check or design constraint), every field has an explicit source, every transition has an explicit trajectory rule, every event type has an explicit parent rule.

---

## Files Modified

| Step | File |
|------|------|
| 1–4, 10–11 | `logging_core.py` |
| 5, 7 | `execution.py` |
| 6 | `runner.py` |
| 8 | `execution_v2.py` |
| 9 | `retry_harness.py` |
