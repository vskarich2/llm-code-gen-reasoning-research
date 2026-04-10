Date: 2026-04-09
Time: 23:30

# LOGGING SYSTEM AUDIT + NEW SYSTEM PLAN

---

# PART 1 — CURRENT SYSTEM AUDIT

## 1.1 Architecture Overview

The current logging system has a **dual-plane architecture**:

| Plane | Class | Scope | Output |
|-------|-------|-------|--------|
| Control plane | `OrchestratorLogger` | Experiment-level events (worker lifecycle, scheduling) | `{experiment_dir}/events.jsonl` |
| Execution plane | `RunLogger` | Per-run events (case lifecycle, LLM calls, results) | `{run_dir}/events.jsonl` + `calls/*.json` + `calls_flat/*.txt` + `run.jsonl` |

Both inherit from `BaseLogger` which provides atomic JSONL append with fsync.

## 1.2 Event Schema (v7 Canonical)

`RunLogger.emit_event()` produces records with 14 structured sections:

```
{
  event_type: str              (legacy compat — "case.end", "call.generate", etc.)
  event_type_canonical: str    (authoritative — "llm_call", "execution_eval", "pipeline_state", "error", "reasoning_eval")
  event_id: int|str            (monotonic per file)
  schema_version: "1.0"
  timestamp: ISO string
  model, condition, case_id, trial, phase  (flat legacy keys)
  work_id, instance_id, attempt            (orchestrator identity)
  payload: dict                             (legacy compat blob)
  run: {run_id, experiment_name, trial, model}
  trace: {trace_id, parent_event_id, trajectory_id, event_index_within_trace}
  context: {case_id, condition, attempt_idx, step, phase, node, edge}
  prompt: {prompt_family, prompt_name, prompt_version, prompt_hash, template_id, variables_hash, tokens_input_estimate}
  llm_call: {call_id, provider, model, temperature, max_tokens, tokens_output_estimate, latency_ms, status, error_type, request_path, response_path, flat_path}
  execution: {ran, passed, score, tests_run, tests_passed, runtime_ms, error}
  reasoning: {evaluated, reasoning_correct, failure_type, confidence}
  artifacts: {code_path, diff_path, stdout_path, stderr_path}
  metrics: {cumulative_calls, cumulative_cost}
  extra: dict  (everything from raw_ev not consumed into canonical sections)
}
```

## 1.3 All Emission Points

| File | Method | What it emits |
|------|--------|---------------|
| `runner.py:137` | `logger.start_case(cid)` | pipeline_state (case_start) |
| `runner.py:151` | `logger.log_structured_error(...)` | case.error.exception |
| `runner.py:156` | `logger.fail_case(...)` | error (case_failed) |
| `runner.py:690` | `logger.log_event("run.start", ...)` | pipeline_state (run_start) |
| `runner.py:735` | `logger.log_event("run.end", ...)` | pipeline_state (run_end) |
| `runner.py:700,728` | `logger.log_lifecycle_event(...)` | worker.start, worker.end |
| `execution_v2.py:464` | `logger.log_structured_error(...)` | case.error.parse |
| `execution_v2.py:1044` | `logger.end_case(...)` | execution_eval (case.end) |
| `execution_v2.py:1049` | `logger.log_run(...)` | debug record (run.jsonl) |
| `retry_v2.py:837` | `logger.end_case(...)` | execution_eval (case.end) |
| `retry_v2.py:842` | `logger.log_run(...)` | debug record (run.jsonl) |
| `llm.py` (via RunLogger) | `logger.log_call(...)` | llm_call (call.generate/classify/oracle) |

## 1.4 All Downstream Readers

| File | What it reads | How |
|------|--------------|-----|
| `materialize.py:build_attempt_table()` | events.jsonl | Reads case.end events, extracts evaluation/reconstruction/classification/ast_eval/oracle sections |
| `v2_metrics.py:compute_v2_metrics()` | Deduplicated rows from merged_run.jsonl | Computes pass rates, v2 categories, classifier dimensions, parse tiers |
| `v2_dashboard.py:write_v2_dashboard()` | Metrics dict from v2_metrics | Renders human-readable text dashboard |
| `live_metrics.py:read_events_safe()` | events.jsonl (per-worker) | Aggregates across workers for live monitoring |
| `orchestrate.py:rebuild_merged_events()` | Per-worker events.jsonl | Deduplicates and merges into merged_events.jsonl |
| Analysis scripts (analysis/) | events.jsonl, merged_events.jsonl | Various CSV/report generation |

## 1.5 Parallel Logging Paths (DUPLICATES)

| Path | System | Purpose | Duplicate? |
|------|--------|---------|------------|
| `RunLogger.log_call()` | logging_core.py | Writes calls/*.json + calls_flat/*.txt + events.jsonl llm_call event | NO — single canonical path |
| `call_logger.emit_call()` | call_logger.py | Writes calls/*.json + calls_flat.txt | **YES — DUPLICATE** of RunLogger.log_call() |
| `RunLogger.log_run()` | logging_core.py | Writes debug record to run.jsonl | **PARALLEL** — debug-only, references canonical event |
| `RunLogger.end_case()` | logging_core.py | Writes case.end event to events.jsonl | NO — canonical |
| `node_logger.log_node_warning()` | node_logger.py | Python stdlib logging only (not WAL) | NO — different purpose (validation warnings) |

**Key duplicate:** `call_logger.py` and `RunLogger.log_call()` BOTH write to `calls/*.json` and flat text files. The call_logger uses GLOBAL STATE (`_run_dir`, `_call_counter`, `_enabled`) while RunLogger uses instance state. In practice, they are not called simultaneously — but the dual existence is confusing and error-prone.

---

# PART 2 — TROUBLE SPOTS

## 2.1 Parent Event ID Threading Issues

**Problem:** Parent event ID must be manually threaded through every call chain.

In `execution_v2.py:run_v2()`:
- `stage_generate()` receives `parent_eid=case_start_eid`
- The generation LLM call returns `gen_event_id`
- This must be passed to `stage_classify()` which calls `log_call()` with `parent_event_id=gen_event_id`
- If `classify_event_id` is non-None, it becomes the new parent for `end_case()`

In `retry_v2.py:run_retry_v2()`:
- `last_parent_eid` is manually tracked through 200+ lines of loop logic
- Updated after each `call_model()` and `_generate_critique()` call
- Easy to lose or pass stale parent IDs

**Symptom:** If any caller forgets to update `last_parent_eid`, the causal chain breaks silently. The schema enforces `parent_event_id is not None` for llm_call/execution_eval/error events — but the parent may point to the WRONG event if the threading is stale.

## 2.2 Global Mutable State in call_logger.py

**Problem:** `call_logger.py` uses 6 module-level globals:
```python
_run_dir: Path | None = None
_calls_dir: Path | None = None
_flat_path: Path | None = None
_call_counter: int = 0
_call_counter_start: int = 0
_enabled: bool = False
```

Plus `_call_context: dict` and `_prompt_provenance: dict | None` which are set-then-consumed between `set_call_context()` and `emit_call()`.

**Symptom:** If two pipeline invocations run in the same process (e.g., shadow mode), the global state from one can leak into the other. The "set context → consume context" pattern is fragile: if an exception occurs between set and consume, context is stale for the next call.

## 2.3 Dual Event Schema (Legacy + Canonical)

**Problem:** Every event has BOTH:
- `event_type`: legacy string (e.g., "case.end") — what `aggregate.py` reads
- `event_type_canonical`: authoritative classification (e.g., "execution_eval")

Plus a `payload` dict that is a THIRD representation of the same data — built by `_build_compat_payload()` for backward compatibility.

**Symptom:** Three places encode the same semantics. Readers must know which to trust. New code reads `event_type_canonical` + structured sections. Old code reads `event_type` + `payload`. Both are in the same record. If they diverge, the record is inconsistent.

## 2.4 Massive Event Records

**Problem:** Each `case.end` event contains the ENTIRE evaluation dict in `extra`. For a single case, this can be 50+ key-value pairs dumped verbatim. The `extra` section is the "everything else" bucket — it's the raw_ev dict minus the few keys consumed into `execution` and `reasoning` sections.

**Symptom:** WAL files are large. The `extra` section is not schema-validated. Its contents vary by condition, V2 version, and whether it's a retry result. Downstream readers must know the internal structure of the evaluation dict to parse `extra`.

## 2.5 Trace/Trajectory State Coupled to Logger

**Problem:** `RunLogger` owns `_current_trace_id`, `_current_trajectory_id`, `_trace_event_counter`. These are set by `start_case()`, cleared by `end_case()`/`fail_case()`, and bumped by `new_trajectory()`.

**Symptom:** The logger is not just a writer — it's a state machine. If a case crashes between `start_case()` and `end_case()`, the trace state is left dangling. The next case's `start_case()` overwrites it, so it's self-healing — but during the crash, any events emitted by error handlers may have stale trace context.

## 2.6 No Graph-Runner WAL Integration

**Problem:** The graph runner's `engine/scheduler.py` uses Python `logging` (stdlib) for lifecycle events (`graph.start`, `node.start`, `node.success`, etc.) but does NOT write to the WAL. The graph runner has its own `EffectLog` (in `effect_wrapper.py`) that writes to a separate `effect_log.jsonl` — a completely independent stream.

**Symptom:** When the graph backend is active, WAL events come from the V2 logging path (via `RunLogger`), but the graph engine's internal lifecycle is invisible in the WAL. You cannot reconstruct which graph nodes ran, in what order, or which failed, from the WAL alone.

## 2.7 run.jsonl is a Parallel Debug Stream

**Problem:** `RunLogger.log_run()` writes to `run.jsonl` — a separate file from `events.jsonl`. It contains prompt lengths, response lengths, parsed reasoning snippets, and references to canonical event IDs.

**Symptom:** Two JSONL files per run (`events.jsonl` + `run.jsonl`) with overlapping but non-identical content. Readers must know which to use. The `run.jsonl` format is not schema-validated and its fields are a subset of what's already in events.jsonl.

---

# PART 3 — PROPOSED NEW LOGGING SYSTEM (PLAN ONLY)

## 3.1 Design Principles

1. **WAL is the single source of truth.** No parallel streams.
2. **Writer is stateless.** No trace/trajectory state in the writer. Context is explicit per event.
3. **No global mutable state.** Writer is passed explicitly via ExecutionContext.
4. **Ownership is clean.** Engine emits engine events. Controller emits controller events. Nodes produce payloads, not events.
5. **Schema is uniform.** One envelope. One version. No legacy compat layer.
6. **Events are small.** Large artifacts (prompts, responses) are referenced by path, not embedded.

## 3.2 Target Event Envelope

```python
@dataclass(frozen=True)
class WALEvent:
    # Identity
    event_id: str           # globally unique (UUID or monotonic)
    event_type: str         # from closed vocabulary
    schema_version: str     # "2.0"
    timestamp: str          # ISO 8601

    # Lineage
    run_id: str
    case_id: str | None
    attempt_index: int | None
    trace_id: str | None
    parent_event_id: str | None

    # Ownership
    emitter: str            # "engine" | "controller" | "node" | "runner"
    node: str | None        # node name if emitter == "node"
    phase: str | None       # "generation" | "classification" | "oracle" | "execution" | etc.

    # Payload
    payload: dict           # event-type-specific structured data
```

## 3.3 Event Type Vocabulary

### Engine Events
- `engine.graph.started` — graph execution begins
- `engine.graph.completed` — graph execution succeeded
- `engine.graph.failed` — graph execution failed
- `engine.node.started` — node execution begins
- `engine.node.completed` — node produced outputs
- `engine.node.failed` — node raised
- `engine.node.skipped` — node skipped (guard false, upstream failed)
- `engine.merge.completed` — outputs merged into state
- `engine.validation.failed` — graph validation failed

### Controller Events
- `controller.attempt.started` — new attempt begins
- `controller.attempt.completed` — attempt pipeline finished
- `controller.retry.decided` — continue/stop decision made
- `controller.critique.generated` — critique text produced
- `controller.result.selected` — best attempt chosen
- `controller.run.completed` — all attempts done, final result assembled

### LLM Call Events
- `llm.call.started` — LLM API call initiated
- `llm.call.completed` — response received
- `llm.call.failed` — API error

### Case Lifecycle Events
- `case.started` — case execution begins
- `case.completed` — case produced final result
- `case.failed` — case crashed

### Run Lifecycle Events
- `run.started` — run begins
- `run.completed` — run ends

## 3.4 Writer Design

```python
class WALWriter:
    """Append-only WAL writer. Stateless. Explicit context per event."""

    def __init__(self, events_path: Path) -> None:
        self.events_path = events_path
        self.counter = 0

    def emit(self, event: WALEvent) -> str:
        """Write event to WAL. Returns event_id. Atomic + fsync."""
        self.counter += 1
        record = asdict(event)
        record["seq"] = self.counter
        line = json.dumps(record, default=str) + "\n"
        # atomic write + fsync
        ...
        return event.event_id
```

Key properties:
- No trace state
- No trajectory state
- No accumulated metrics
- No global singletons
- Writer is created per-run and passed via ExecutionContext

## 3.5 Parent ID Strategy

**Current problem:** Manual threading of `last_parent_eid` through 200+ lines.

**New approach:** The engine scheduler automatically threads parent IDs:
- `engine.graph.started` is the root event
- Each `engine.node.started` gets `parent_event_id = graph_started_event_id`
- Each `engine.node.completed` gets `parent_event_id = node_started_event_id`
- LLM calls within a node get `parent_event_id = node_started_event_id`

The controller does the same for attempt lifecycle:
- `controller.attempt.started` gets `parent_event_id = controller.run.started`
- Each graph execution within an attempt gets `parent_event_id = attempt_started_event_id`

This is automatic — no manual threading needed.

## 3.6 Large Artifact Handling

Prompts and responses are NOT embedded in WAL events. Instead:
- `llm.call.completed` includes `artifact_ref: "calls/000042.json"`
- The calls directory continues to hold full prompt/response files
- WAL event holds only: model, latency_ms, prompt_hash, response_hash, artifact_ref

## 3.7 Migration Path

### Phase 1: Add WALWriter to graph-runner
- Create `side_projects/graph_runner/runtime/wal_writer.py`
- WALWriter follows the v2.0 schema
- Engine scheduler emits engine events through WALWriter
- Controller emits controller events through WALWriter
- Graph-runner has its own clean WAL stream

### Phase 2: Dual-emit during transition
- When graph backend is active, BOTH old RunLogger AND new WALWriter write
- Old WAL (events.jsonl) continues for V2 compat
- New WAL (wal.jsonl) contains clean v2.0 events
- Downstream readers updated to prefer new WAL when available

### Phase 3: V2 retirement
- Once graph runner is fully canonical, old RunLogger is removed
- WALWriter becomes the only writer
- events.jsonl uses v2.0 schema exclusively
- Old analysis scripts updated to read v2.0 schema

### Phase 4: call_logger.py removal
- Once RunLogger.log_call() is the only LLM call logger, call_logger.py is deleted
- Or: call_logger.py functionality is absorbed into WALWriter's LLM call event emission

## 3.8 Downstream Reader Updates

| Current Reader | Change Needed |
|---|---|
| `materialize.py` | Add v2.0 schema parser alongside existing v7 parser. Select based on `schema_version` field. |
| `v2_metrics.py` | No change during Phase 1-2. Phase 3: update to read v2.0 schema. |
| `v2_dashboard.py` | No change during Phase 1-2. Phase 3: update to read v2.0 metrics. |
| `live_metrics.py` | No change during Phase 1-2. Phase 3: aggregate from v2.0 events. |
| `orchestrate.py` (event merging) | No change during Phase 1-2. Phase 3: merge v2.0 events by event_id. |

## 3.9 What This Fixes

| Problem | Fix |
|---|---|
| Parent ID threading | Automatic: engine/controller own parent chains |
| Global state in call_logger | Eliminated: WALWriter is stateless, passed via context |
| Dual schema (legacy + canonical) | Eliminated: one schema, one vocabulary |
| Massive event records | Fixed: large artifacts referenced, not embedded |
| Trace state in logger | Eliminated: context is explicit per event |
| No graph-runner WAL | Fixed: engine emits structured lifecycle events |
| run.jsonl parallel stream | Eliminated: all debug info in WAL events or artifact refs |

## 3.10 Remaining Blockers

1. **V2 pipeline must keep working.** The new WAL is graph-runner-only in Phase 1. V2 keeps its RunLogger until retirement.
2. **Analysis scripts.** All scripts in `analysis/` read the v7 schema. They need migration in Phase 3.
3. **Orchestrator event merging.** The manifest/worker merge system in orchestrate.py deduplicates by event_id format. New WAL event IDs must be compatible with this or the merge logic needs updating.
4. **Experiment reproducibility.** Old experiment logs must remain readable. The new system must not break parsing of historical WAL files.
