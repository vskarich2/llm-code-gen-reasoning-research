# Experiment Orchestrator + Centralized Logging — System Design v5

**Date:** 2026-03-29
**Status:** Plan (final — ready for implementation)
**Replaces:** v1–v4, `scripts/run_ablation_leg_8t.sh`, `scripts/update_dashboards.py`, `call_logger.py`

---

## SECTION 1 — Architecture

```
┌─────────────────────┐
│  experiment.yaml     │
└──────────┬──────────┘
           │
┌──────────▼──────────────────────────────────────┐
│  Orchestrator (orchestrate.py)                   │
│                                                  │
│  Uses OrchestratorLogger → writes to             │
│    experiments/{name}/events.jsonl                │
│                                                  │
│  Submits ONLY serializable args to pool          │
│  Workers create RunLogger LOCALLY                │
└──────────┬──────────────────────────────────────┘
           │
    ┌──────▼──────┐
    │ ProcessPool  │
    └─┬───┬───┬──┘
      │   │   │
   ┌──▼┐ ┌▼──┐┌▼──┐
   │W1 │ │W2 ││W3 │
   └┬──┘ └┬──┘└┬──┘
   ┌▼─────▼────▼───────────────────────────┐
   │  Per-Run Directory                     │
   │  events.jsonl  (execution timeline)    │
   │  calls/        (canonical JSON)        │
   │  calls_flat/   (derived text)          │
   │  metadata.json (static identity)       │
   │  metrics.json  (derived at finalize)   │
   └────────────────┬──────────────────────┘
                    │
   ┌────────────────▼──────────────────────┐
   │  Aggregator                            │
   │  Reads ALL events.jsonl files          │
   │  Groups by trace_id, case_id, model    │
   └───────────────────────────────────────┘
```

### Two logging planes, one schema

| Plane | Logger | File | Contains |
|-------|--------|------|----------|
| Control | OrchestratorLogger | `experiments/{name}/events.jsonl` | Scheduling, preflight, worker lifecycle |
| Execution | RunLogger | `.../{model}/{cond}/trial_{n}/events.jsonl` | Run lifecycle, case execution, LLM calls |

Both use identical event schema (Section 4). Both produce events.jsonl. The aggregator reads all of them.

### Cross-file ordering

event_id provides STRICT ordering within a single events.jsonl file. Cross-file ordering is BEST-EFFORT using timestamp. The global timeline reconstructed by merging experiment-level and run-level events is APPROXIMATE and intended for debugging and visualization, not strict deterministic replay. Within any single file, event_id is canonical.

### Stdout

- `sys.stdout.reconfigure(line_buffering=True)` at process start
- All `print()` use `flush=True`
- Every `print()` corresponds to a structured event already written
- No operationally meaningful information exists only in stdout

---

## SECTION 2 — ID System

| ID | Type | Scope | Purpose | Created by |
|----|------|-------|---------|-----------|
| `run_id` | `str` | Per (model, condition, trial) | Groups all events in one run | Orchestrator |
| `trace_id` | `str` (UUID hex) | Per case execution | Groups all events for one case: start, calls, parse, exec, classify, end | RunLogger.start_case() |
| `event_id` | `int` (monotonic) | Per events.jsonl file | Strict ordering within one file | Logger, auto-incremented |
| `call_id` | `int` (monotonic) | Per run | Links events to files in calls/ and calls_flat/ | RunLogger.log_call() |

Rules:
- `event_id` is ordering only. Strict within one file. Not meaningful across files.
- `trace_id` is the primary debugging and replay key. It is generated via UUID and is globally unique across all runs in the experiment. Querying by trace_id alone is sufficient to reconstruct a full causal trace — no need to join on run_id.
- `call_id` is file linkage. `call_id=3` → `calls/000003.json` + `calls_flat/000003_generate.txt`.
- `run_id` groups all events and files for one run.

---

## SECTION 3 — Logging API

### BaseLogger

```python
class BaseLogger:
    """Shared event-writing logic. OrchestratorLogger and RunLogger inherit."""

    def __init__(self, events_path: Path):
        self._events_file = open(events_path, "a", encoding="utf-8")
        self._event_counter = 0

    def _write_event(self, event: dict) -> int:
        """Validate, assign event_id, write, flush. Returns event_id."""
        assert event["event_type"] in VALID_EVENT_TYPES
        assert event.get("phase") in VALID_PHASES
        self._event_counter += 1
        event["event_id"] = self._event_counter
        line = json.dumps(event, default=str) + "\n"
        self._events_file.write(line)
        self._events_file.flush()
        if event["event_type"] in _FSYNC_EVENT_TYPES:
            os.fsync(self._events_file.fileno())
        return self._event_counter

    def close(self) -> None:
        self._events_file.close()
```

### OrchestratorLogger

```python
class OrchestratorLogger(BaseLogger):
    """Control plane logger. Created in orchestrator main process only."""

    def __init__(self, experiment_dir: Path):
        super().__init__(experiment_dir / "events.jsonl")

    def log_event(self, event_type: str, payload: dict) -> int:
        return self._write_event({
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "run_id": None,
            "trace_id": None,
            "trial": None,
            "model": None,
            "condition": None,
            "case_id": None,
            "phase": "orchestrator",
            "payload": payload,
        })
```

### RunLogger

```python
class RunLogger(BaseLogger):
    """Execution plane logger. Created LOCALLY inside each worker process.
    NEVER pickled. NEVER passed through ProcessPoolExecutor."""

    def __init__(self, run_dir: Path, run_id: str,
                 model: str, condition: str, trial: int):
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "calls").mkdir(exist_ok=True)
        (run_dir / "calls_flat").mkdir(exist_ok=True)
        super().__init__(run_dir / "events.jsonl")
        self._run_dir = run_dir
        self._run_id = run_id
        self._model = model
        self._condition = condition
        self._trial = trial
        self._call_counter = 0
        self._current_trace_id: str | None = None
        write_json_atomic(run_dir / "metadata.json", {
            "run_id": run_id, "model": model, "condition": condition,
            "trial": trial, "start_time": datetime.now().isoformat(),
        })

    def start_case(self, case_id: str) -> str:
        """Begin case execution. Creates trace_id. Logs case.start. Returns trace_id."""
        self._current_trace_id = uuid.uuid4().hex
        self.log_event("case.start", {}, case_id=case_id, phase="case")
        return self._current_trace_id

    def end_case(self, case_id: str, payload: dict) -> int:
        """End case. Logs case.end. Clears trace_id."""
        event_id = self.log_event("case.end", payload, case_id=case_id, phase="case")
        self._current_trace_id = None
        return event_id

    def fail_case(self, case_id: str, payload: dict) -> int:
        """Record case failure. Logs case.failed. Clears trace_id."""
        event_id = self.log_event("case.failed", payload, case_id=case_id, phase="case")
        self._current_trace_id = None
        return event_id

    def log_event(self, event_type: str, payload: dict,
                  case_id: str | None = None,
                  phase: str | None = None) -> int:
        """Write structured event. Injects run identity and current trace_id.

        Raises RuntimeError if event_type requires trace_id but none is active.
        """
        if event_type in REQUIRES_TRACE and self._current_trace_id is None:
            raise RuntimeError(
                f"trace_id is None but event_type '{event_type}' requires an active trace. "
                f"Call start_case() before emitting case-level events."
            )
        if phase is None:
            phase = _infer_phase(event_type)
        return self._write_event({
            "event_type": event_type,
            "timestamp": datetime.now().isoformat(),
            "run_id": self._run_id,
            "trace_id": self._current_trace_id,
            "trial": self._trial,
            "model": self._model,
            "condition": self._condition,
            "case_id": case_id,
            "phase": phase,
            "payload": payload,
        })

    def log_call(self, model: str, prompt: str, response: str,
                 elapsed_seconds: float, case_id: str, phase: str,
                 error: str | None = None,
                 prompt_assembly: dict | None = None) -> int:
        """Log one LLM call. Returns call_id.

        Writes three outputs from ONE in-memory record:
        1. calls/{call_id:06d}.json
        2. calls_flat/{call_id:06d}_{phase}.txt
        3. events.jsonl entry

        phase must be a VALID_PHASES value.
        event_type is derived via PHASE_TO_CALL_EVENT_TYPE mapping.
        """
        self._call_counter += 1
        call_id = self._call_counter

        event_type = PHASE_TO_CALL_EVENT_TYPE[phase]

        record = {
            "call_id": call_id,
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "phase": phase,
            "case_id": case_id,
            "condition": self._condition,
            "trial": self._trial,
            "run_id": self._run_id,
            "trace_id": self._current_trace_id,
            "prompt_raw": prompt,
            "response_raw": response,
            "prompt_length": len(prompt),
            "response_length": len(response),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "error": error,
            "prompt_assembly": prompt_assembly,
        }

        # Write canonical JSON (atomic)
        json_path = self._run_dir / "calls" / f"{call_id:06d}.json"
        write_json_atomic(json_path, record)

        # Write derived flat text (atomic, from same record)
        flat_path = self._run_dir / "calls_flat" / f"{call_id:06d}_{phase}.txt"
        write_text_atomic(flat_path, render_call_flat(record))

        # Write event (references call_id, does NOT embed prompt/response)
        self.log_event(event_type, {
            "call_id": call_id,
            "latency_ms": round(elapsed_seconds * 1000),
            "prompt_length": len(prompt),
            "response_length": len(response),
            "error": error,
        }, case_id=case_id, phase=phase)

        return call_id

    def log_metric(self, name: str, value, context: dict | None = None) -> int:
        return self.log_event("metric.record", {
            "name": name, "value": value, "context": context or {},
        }, phase="evaluation")

    def finalize(self) -> dict:
        """Close logger. Derive metrics.json from events.jsonl. Validate. Return stats."""
        # Read back events.jsonl to compute metrics
        events = read_events(self._run_dir / "events.jsonl")
        case_ends = [e for e in events if e["event_type"] == "case.end"]
        total = len(case_ends)
        passes = sum(1 for e in case_ends if e["payload"].get("pass"))
        stats = {
            "pass_rate": passes / total if total else 0,
            "total_cases": total,
            "total_pass": passes,
        }
        write_json_atomic(self._run_dir / "metrics.json", stats)

        # Write calls_index.json
        calls_index = []
        for e in events:
            if e["event_type"] in CALL_EVENT_TYPES:
                cid = e["payload"]["call_id"]
                calls_index.append({
                    "call_id": cid,
                    "case_id": e["case_id"],
                    "trace_id": e["trace_id"],
                    "phase": e["phase"],
                    "json": f"calls/{cid:06d}.json",
                    "flat": f"calls_flat/{cid:06d}_{e['phase']}.txt",
                })
        write_json_atomic(self._run_dir / "calls_index.json", calls_index)

        # Validate
        ok, errors = self.validate()
        if not ok:
            raise RuntimeError(f"Run validation failed: {errors}")

        self.close()
        return stats

    def validate(self) -> tuple[bool, list[str]]:
        errors = []
        events = read_events(self._run_dir / "events.jsonl")
        json_count = len(list((self._run_dir / "calls").glob("*.json")))
        flat_count = len(list((self._run_dir / "calls_flat").glob("*.txt")))
        if json_count != flat_count:
            errors.append(f"calls mismatch: {json_count} JSON vs {flat_count} flat")
        if not events:
            errors.append("events.jsonl is empty")
        elif events[0]["event_type"] != "run.start":
            errors.append(f"first event is {events[0]['event_type']}, expected run.start")
        elif events[-1]["event_type"] not in ("run.end", "run.failed"):
            errors.append(f"last event is {events[-1]['event_type']}, expected run.end or run.failed")
        # Check case lifecycle
        open_traces = {}
        for e in events:
            if e["event_type"] == "case.start":
                tid = e["trace_id"]
                if tid in open_traces:
                    errors.append(f"duplicate case.start for trace_id {tid}")
                open_traces[tid] = e["case_id"]
            elif e["event_type"] in ("case.end", "case.failed"):
                tid = e["trace_id"]
                if tid not in open_traces:
                    errors.append(f"case.end/failed without case.start for trace_id {tid}")
                else:
                    del open_traces[tid]
        if open_traces:
            errors.append(f"unclosed cases: {list(open_traces.values())}")
        # Check trace_id invariant: case-level events must have trace_id
        for e in events:
            if e["event_type"] in REQUIRES_TRACE and e["trace_id"] is None:
                errors.append(
                    f"event_id={e['event_id']} type={e['event_type']} has trace_id=None "
                    f"(case_id={e.get('case_id')})"
                )
        # Check event_id monotonicity
        ids = [e["event_id"] for e in events]
        if ids != list(range(1, len(ids) + 1)):
            errors.append("event_ids not strictly monotonic from 1")
        # Check no legacy file
        if (self._run_dir / "calls_flat.txt").exists():
            errors.append("legacy calls_flat.txt still exists")
        return (len(errors) == 0, errors)
```

---

## SECTION 4 — Event Schema

Every line in every events.jsonl:

```json
{
  "event_id": 5,
  "timestamp": "2026-03-29T10:00:01.234567",
  "run_id": "gpt-5-mini_baseline_t1_a3f8c2d1",
  "trace_id": "e7a3b9c2d1f04567",
  "trial": 1,
  "model": "gpt-5-mini",
  "condition": "baseline",
  "case_id": "alias_config_a",
  "phase": "generation",
  "event_type": "call.generate",
  "payload": { ... }
}
```

For orchestrator events: `run_id`, `trace_id`, `case_id`, `trial`, `model`, `condition` are all null. `phase` is `"orchestrator"`.

For run-level events (run.start, run.end): `trace_id` and `case_id` are null.

For case/call events: `trace_id` is always set.

### VALID_EVENT_TYPES

```python
VALID_EVENT_TYPES = frozenset({
    # Orchestrator (control plane)
    "orchestrator.start",
    "orchestrator.schedule",
    "orchestrator.worker_start",
    "orchestrator.worker_end",
    "orchestrator.worker_failed",
    "orchestrator.abort",
    "orchestrator.complete",
    "orchestrator.preflight_pass",
    "orchestrator.preflight_fail",

    # Run (execution plane)
    "run.start",
    "run.end",
    "run.failed",

    # Case
    "case.start",
    "case.end",
    "case.failed",

    # LLM calls
    "call.generate",
    "call.classify",
    "call.other",

    # Pipeline stages
    "parse.result",
    "execution.result",

    # Metrics
    "metric.record",

    # Validation
    "validation.pass",
    "validation.fail",
})
```

### VALID_PHASES

```python
VALID_PHASES = frozenset({
    "orchestrator",
    "run",
    "case",
    "generation",
    "classification",
    "parsing",
    "reconstruction",
    "evaluation",
    "validation",
})
```

### Phase-to-event-type mapping for calls

```python
PHASE_TO_CALL_EVENT_TYPE = {
    "generation": "call.generate",
    "classification": "call.classify",
}
```

`log_call()` uses this mapping. If `phase` is not in the map, event_type defaults to `"call.other"`. This is the ONLY place where phase and event_type are related for calls. No implicit `"call.{phase}"` construction.

### Phase inference for log_event

```python
_PHASE_INFERENCE = {
    "orchestrator.": "orchestrator",
    "run.": "run",
    "case.": "case",
    "call.generate": "generation",
    "call.classify": "classification",
    "call.other": "generation",
    "parse.": "parsing",
    "execution.": "evaluation",
    "metric.": "evaluation",
    "validation.": "validation",
}

def _infer_phase(event_type: str) -> str:
    for prefix, phase in _PHASE_INFERENCE.items():
        if event_type.startswith(prefix):
            return phase
    raise ValueError(f"Cannot infer phase for event_type: {event_type}")
```

### CALL_EVENT_TYPES

```python
CALL_EVENT_TYPES = frozenset({"call.generate", "call.classify", "call.other"})
```

### REQUIRES_TRACE

Event types that MUST have `trace_id != None`. These are case-level events that are meaningless without trace context.

```python
REQUIRES_TRACE = frozenset({
    "case.start",
    "case.end",
    "case.failed",
    "call.generate",
    "call.classify",
    "call.other",
    "parse.result",
    "execution.result",
})
```

Enforcement: `RunLogger.log_event()` raises `RuntimeError` if `event_type in REQUIRES_TRACE` and `self._current_trace_id is None`. This makes it structurally impossible to emit a case-level event outside of a `start_case()` / `end_case()` bracket.

### _FSYNC_EVENT_TYPES

```python
_FSYNC_EVENT_TYPES = frozenset({
    "run.start", "run.end", "run.failed",
    "case.failed",
    "orchestrator.start", "orchestrator.complete", "orchestrator.abort",
    "orchestrator.worker_failed",
})
```

---

## SECTION 5 — Orchestrator Lifecycle

```
orchestrator.start            experiment begins
orchestrator.preflight_pass   each preflight check that passes
orchestrator.preflight_fail   → triggers orchestrator.abort (experiment stops)
orchestrator.schedule         one per work item
orchestrator.worker_start     worker process began (optional, emitted if detectable)
orchestrator.worker_end       worker returned successfully
orchestrator.worker_failed    worker raised exception (a specific run failed)
orchestrator.complete         experiment finished (even if some runs failed)
orchestrator.abort            experiment stopped early (preflight failure, fatal error)
```

Final event is ALWAYS one of:
- `orchestrator.complete` — normal finish (some runs may have failed)
- `orchestrator.abort` — experiment stopped before completion

`orchestrator.worker_failed` is per-run, not experiment-level. It does NOT terminate the experiment.

### No-duplication contract

| Fact | Authoritative source | Echoed where? |
|------|---------------------|---------------|
| Preflight result | experiment events.jsonl (orchestrator.preflight_*) | Nowhere else |
| Worker scheduled | experiment events.jsonl (orchestrator.schedule) | manifest.json caches status |
| Worker completed/failed | experiment events.jsonl (orchestrator.worker_end/failed) | manifest.json caches status |
| Case pass/fail | run events.jsonl (case.end) | metrics.json derives from this |
| LLM call details | calls/{id}.json (canonical) + run events.jsonl (call.* with call_id reference) | calls_flat/ derived |
| Run pass_rate | run events.jsonl (run.end payload) | manifest.json may echo for convenience |

If any derived artifact disagrees with events.jsonl, events.jsonl wins. manifest.json is a coordination cache. metrics.json is a derived summary generated from events.jsonl at finalize time and is never treated as authoritative.

---

## SECTION 6 — Trace Retrieval

trace_id is the primary debugging and replay key.

trace_id is generated via `uuid.uuid4().hex`. Uniqueness is global across all runs in the experiment and across experiments. Querying by trace_id alone is sufficient to reconstruct a full causal trace. No need to join on run_id or know which file to look in.

Given `trace_id = "e7a3b9c2d1f04567"`:

```
grep "e7a3b9c2d1f04567" experiments/*/events.jsonl experiments/*/*/*/*/events.jsonl

Results (ordered by event_id within file):

  case.start        → case_id, timestamp
  call.generate     → call_id=1 → calls/000001.json (full prompt + response)
  parse.result      → format, error
  execution.result  → pass, score, ran
  call.classify     → call_id=2 → calls/000002.json (full classifier prompt + response)
  case.end          → pass, score, code_correct, reasoning_correct, failure_type
```

Events reference call_id for file linkage. Events do NOT embed full prompts or responses.

---

## SECTION 7 — File Layout

```
experiments/
  baseline_vs_leg_v2/
    experiment.yaml                     FROZEN CONFIG (written once)
    manifest.json                       COORDINATION CACHE (not timeline)
    events.jsonl                        CONTROL PLANE TIMELINE

    gpt-5.4-mini/
      baseline/
        trial_1/
          metadata.json                 STATIC (written once)
          events.jsonl                  EXECUTION PLANE TIMELINE (authoritative)
          calls/
            000001.json                 CANONICAL per-call
            000002.json
          calls_flat/
            000001_generation.txt       DERIVED from calls/000001.json
            000002_classification.txt
          calls_index.json              DERIVED at finalize
          metrics.json                  DERIVED from events.jsonl at finalize

    aggregated/                         DERIVED from all events.jsonl files
      per_model.json
      per_condition.json
      per_trial.json
      per_trace.json
      dashboard.json
```

### Flat file naming

`{call_id:06d}_{phase}.txt` where phase is the VALID_PHASES value used in log_call.

Examples: `000001_generation.txt`, `000002_classification.txt`

---

## SECTION 8 — File Write Safety

### events.jsonl

- Opened in append text mode (`"a"`, encoding `"utf-8"`) at logger init
- One JSON object per line, terminated by `\n`
- `file.write(json.dumps(event, default=str) + "\n")` — one write call
- `file.flush()` after every write
- `os.fsync(file.fileno())` after events in `_FSYNC_EVENT_TYPES`
- Handle held open for logger lifetime, closed in `finalize()` or `close()`

### calls/{id}.json and calls_flat/{id}_{phase}.txt

- Written via `write_json_atomic` / `write_text_atomic`: open temp → write → flush → fsync → `os.replace(tmp, final)`
- Both written in same `log_call()` invocation from same in-memory record
- If either write fails, `log_call()` raises `RuntimeError`

### render_call_flat(record) → str

Single function. Only place that defines flat format. In logging_core.py.

```
=== CALL 000001 ===
MODEL: gpt-5-mini
PHASE: generation
CASE_ID: alias_config_a
CONDITION: baseline
TRIAL: 1
RUN_ID: gpt-5-mini_baseline_t1_a3f8c2d1
TRACE_ID: e7a3b9c2d1f04567
TIMESTAMP: 2026-03-29T10:00:01
LATENCY_MS: 2341

--- PROMPT ---
<full prompt text>

--- RESPONSE ---
<full response text>
```

### Directory creation

Logger `__init__` creates all directories with `parents=True, exist_ok=True`. No creation after init.

### No cross-process handles

Each logger created inside its own process. Nothing crosses ProcessPoolExecutor.

---

## SECTION 9 — Orchestrator

```python
def main():
    sys.stdout.reconfigure(line_buffering=True)

    config = load_experiment_config(args.config)
    validate_config(config)

    experiment_dir = Path(config.output.base_dir) / config.experiment.name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(experiment_dir / "experiment.yaml", config)

    orch_logger = OrchestratorLogger(experiment_dir)
    orch_logger.log_event("orchestrator.start", {
        "config_hash": config.hash,
        "models": [m.name for m in config.models.generation],
        "conditions": config.conditions,
        "trials": config.trials,
        "parallelism": config.execution.parallelism,
    })

    # Preflight — orchestrator level
    try:
        run_preflight(config)
        orch_logger.log_event("orchestrator.preflight_pass", {"checks": "all"})
    except PreflightError as e:
        orch_logger.log_event("orchestrator.preflight_fail", {"error": str(e)})
        orch_logger.log_event("orchestrator.abort", {"reason": "preflight_failure"})
        orch_logger.close()
        print(f"PREFLIGHT FAILED: {e}", flush=True)
        sys.exit(1)

    # Generate work items
    work_items = generate_work_items(config, experiment_dir)
    for item in work_items:
        orch_logger.log_event("orchestrator.schedule", {
            "run_id": item.run_id,
            "model": item.model,
            "condition": item.condition,
            "trial": item.trial,
            "run_dir": str(item.run_dir),
        })

    # Submit — ONLY serializable arguments
    manifest = {}
    completed_count = 0
    failed_count = 0

    with ProcessPoolExecutor(max_workers=config.execution.parallelism) as pool:
        futures = {
            pool.submit(
                run_single,
                run_dir=str(item.run_dir),
                run_id=item.run_id,
                model=item.model,
                condition=item.condition,
                trial=item.trial,
                config=config,
            ): item
            for item in work_items
        }

        total = len(futures)
        done = 0
        for future in as_completed(futures):
            item = futures[future]
            done += 1
            try:
                result = future.result()
                completed_count += 1
                orch_logger.log_event("orchestrator.worker_end", {
                    "run_id": item.run_id,
                    "status": "completed",
                    "pass_rate": result.pass_rate,
                    "total_cases": result.stats.get("total_cases", 0),
                })
                manifest[item.run_id] = {
                    "status": "completed",
                    "pass_rate": result.pass_rate,
                }
                print(f"[{done}/{total}] {item.run_id} DONE ({result.pass_rate:.1%})", flush=True)

            except Exception as e:
                failed_count += 1
                orch_logger.log_event("orchestrator.worker_failed", {
                    "run_id": item.run_id,
                    "error": f"{type(e).__name__}: {e}",
                })
                manifest[item.run_id] = {
                    "status": "failed",
                    "error": str(e),
                }
                print(f"[{done}/{total}] {item.run_id} FAILED: {e}", flush=True)

    write_json(experiment_dir / "manifest.json", manifest)

    orch_logger.log_event("orchestrator.complete", {
        "total": total,
        "completed": completed_count,
        "failed": failed_count,
    })
    orch_logger.close()

    # Aggregate
    aggregate_experiment(experiment_dir)

    print(f"Experiment complete: {completed_count} succeeded, {failed_count} failed", flush=True)
```

---

## SECTION 10 — Worker

```python
def run_single(run_dir: str, run_id: str, model: str,
               condition: str, trial: int, config) -> RunResult:

    logger = RunLogger(
        run_dir=Path(run_dir),
        run_id=run_id,
        model=model,
        condition=condition,
        trial=trial,
    )

    cases = load_cases(config.cases.source)

    logger.log_event("run.start", {
        "total_cases": len(cases),
        "config_hash": config.hash,
        "git_hash": get_git_hash(),
        "model_temperature": config.get_model_temperature(model),
    }, phase="run")

    for case in cases:
        case_id = case["id"]
        trace_id = logger.start_case(case_id)

        try:
            # --- Generation ---
            prompt = build_prompt(case, condition)
            gen_start = time.monotonic()
            raw_output = call_model(prompt, model=model)
            gen_elapsed = time.monotonic() - gen_start

            gen_call_id = logger.log_call(
                model=model,
                prompt=prompt,
                response=raw_output,
                elapsed_seconds=gen_elapsed,
                case_id=case_id,
                phase="generation",
            )

            # --- Parse ---
            parsed = parse_and_reconstruct(raw_output, case)
            logger.log_event("parse.result", {
                "format": parsed.get("response_format"),
                "error": parsed.get("parse_error"),
                "code_length": len(parsed.get("code") or ""),
            }, case_id=case_id, phase="parsing")

            # --- Execute ---
            code = parsed.get("code") or ""
            exec_result = exec_evaluate(case, code)
            logger.log_event("execution.result", {
                "pass": exec_result["pass"],
                "score": exec_result["score"],
                "ran": exec_result["execution"]["ran"],
                "assembly_used": exec_result["execution"].get("assembly_used", False),
                "assembly_error": exec_result["execution"].get("assembly_error", False),
            }, case_id=case_id, phase="evaluation")

            # --- Classify ---
            classify_prompt = build_classify_prompt(case, code, parsed.get("reasoning", ""))
            classify_start = time.monotonic()
            classify_raw = call_model(classify_prompt, model=config.models.evaluator.name, raw=True)
            classify_elapsed = time.monotonic() - classify_start

            classify_call_id = logger.log_call(
                model=config.models.evaluator.name,
                prompt=classify_prompt,
                response=classify_raw,
                elapsed_seconds=classify_elapsed,
                case_id=case_id,
                phase="classification",
            )

            classify_result = parse_classify_output(classify_raw)

            # --- End case ---
            logger.end_case(case_id, {
                "pass": exec_result["pass"],
                "score": exec_result["score"],
                "code_correct": exec_result["pass"],
                "reasoning_correct": classify_result.get("reasoning_correct"),
                "failure_type": classify_result.get("failure_type"),
                "gen_call_id": gen_call_id,
                "classify_call_id": classify_call_id,
            })

        except Exception as e:
            logger.fail_case(case_id, {
                "error": f"{type(e).__name__}: {e}",
            })

    stats = logger.finalize()
    return RunResult(pass_rate=stats["pass_rate"], stats=stats)
```

---

## SECTION 11 — Aggregator

### What it reads

ALL events.jsonl files:
- `experiments/{name}/events.jsonl` (control plane)
- `experiments/{name}/{model}/{cond}/trial_{n}/events.jsonl` (all execution planes)

### Grouping

| Group by | Yields |
|----------|--------|
| `trace_id` | Complete causal trace for one case execution (primary analysis unit) |
| `case_id` | All executions of one case across trials/models |
| `model` | All events for one model |
| `condition` | All events for one condition |
| `model + condition` | One cell in experiment matrix |
| `model + condition + trial` | One run |

### Metrics computed

From `case.end` / `case.failed`:
- Pass rate, failure rate, score distribution per model/condition/trial
- Failure type distribution
- Per-case stability across trials

From `call.generate` / `call.classify`:
- Average latency by phase and model
- API error rate and timeout frequency
- Total calls by model and phase

From `parse.result`:
- Parse failure rate by model and condition
- Response format distribution

From `execution.result`:
- ran_rate, assembly_error_rate

From trace-level grouping (trace_id):
- LEG analysis: reasoning_correct vs code_correct per trace
- Per-trace latency budget (generation + classification)
- Cases where parse failed but execution attempted
- Classifier disagreement patterns

trace_id grouping is first-class, not optional. LEG analysis is computed per trace_id. This is the fundamental unit of benchmark measurement.

### What it writes

- `aggregated/per_model.json`
- `aggregated/per_condition.json`
- `aggregated/per_trial.json`
- `aggregated/per_trace.json`
- `aggregated/dashboard.json`

---

## SECTION 12 — Validation

### RunLogger.finalize()

1. events.jsonl exists, ≥ 2 events
2. `len(calls/*.json) == len(calls_flat/*.txt)`
3. Every call.* event has call_id with matching file in calls/
4. Every case.start has exactly one case.end or case.failed with same trace_id
5. All events between case.start and case.end share same trace_id
6. Every event with event_type in REQUIRES_TRACE has trace_id != None
7. First event is run.start (event_id=1)
8. Last event is run.end or run.failed
9. event_ids strictly monotonic from 1, no gaps
10. No calls_flat.txt exists
11. metrics.json derived from events.jsonl, not independently written

### OrchestratorLogger at close

1. events.jsonl exists
2. First event is orchestrator.start
3. Last event is orchestrator.complete or orchestrator.abort
4. Every orchestrator.schedule run_id has at most one worker_end or worker_failed

Any failure → RuntimeError.

---

## SECTION 13 — Migration

### Step 0: Convert existing logs
`scripts/migrate_call_logs.py` — JSON → flat, delete calls_flat.txt, idempotent

### Step 1: logging_core.py
BaseLogger, OrchestratorLogger, RunLogger, render_call_flat, all enums, write helpers. Replaces call_logger.py.

### Step 2: orchestrate.py
Config, preflight, pool, OrchestratorLogger, manifest. Serializable args only.

### Step 3: Wire workers
RunLogger locally. start_case/end_case with trace_id. log_call replaces emit_call. log_event replaces emit_event.

### Step 4: aggregate.py
Full event stream. trace_id grouping. LEG analysis.

### Step 5: Delete legacy
call_logger.py, live_metrics.py:emit_event, bash scripts, validate_smoke.py, all calls_flat.txt references.

### Step 6: Makefile
```makefile
run:
    .venv/bin/python orchestrate.py --config experiments/my_experiment.yaml
aggregate:
    .venv/bin/python aggregate.py --experiment experiments/my_experiment/
validate:
    .venv/bin/python validate_cases_v2.py
```

---

## SECTION 14 — Success Criteria

1. `orchestrate.py --config X` runs full experiment, no bash
2. ALL logging through logging_core — no other code writes log files
3. Control plane: experiment events.jsonl records scheduling, preflight, worker lifecycle
4. Execution plane: per-run events.jsonl records case execution, calls, results
5. Identical schema across planes with event_id, timestamp, trace_id
6. trace_id is globally unique, primary query key, requires no join
7. Given trace_id: full chain reconstructible (prompt → response → parse → exec → classify → result)
8. Workers create loggers locally — nothing crosses process boundary
9. Preflight logged at orchestrator level only
10. manifest.json is coordination cache, not execution truth
11. metrics.json derived from events.jsonl at finalize, never independent
12. `len(calls/*.json) == len(calls_flat/*.txt)` validated at run end
13. No calls_flat.txt
14. No information only in stdout
15. event_id strict within file, cross-file ordering is best-effort approximate
16. orchestrator.complete or orchestrator.abort is always the final orchestrator event
17. orchestrator.worker_failed is per-run, does not terminate experiment
18. Aggregator consumes full event stream, trace_id grouping is first-class
19. No naming inconsistency between event_type and phase (PHASE_TO_CALL_EVENT_TYPE resolves)
20. Same config + same code = same experiment
