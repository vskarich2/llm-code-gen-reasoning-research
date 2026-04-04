# Experiment Orchestrator + Centralized Logging — System Design v2 (FINAL)

**Date:** 2026-03-29
**Status:** Plan (no code yet)
**Replaces:** `scripts/run_ablation_leg_8t.sh`, `scripts/update_dashboards.py`, `call_logger.py`, all fragmented logging

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
│  Creates OrchestratorLogger (writes to           │
│  experiment-level events.jsonl)                   │
│                                                  │
│  1. Load + validate config                       │
│  2. Run preflight (logged as orchestrator events)│
│  3. Generate work items                          │
│  4. Submit SERIALIZABLE args to ProcessPool      │
│  5. Log scheduling, completion, failure events   │
│  6. Write manifest.json (coordination cache)     │
│  7. Call aggregator                              │
└──────────┬──────────────────────────────────────┘
           │
    ┌──────▼──────┐
    │ ProcessPool  │
    └─┬───┬───┬──┘
      │   │   │
   ┌──▼┐ ┌▼──┐┌▼──┐   Each worker:
   │W1 │ │W2 ││W3 │   1. Creates RunLogger LOCALLY
   └┬──┘ └┬──┘└┬──┘   2. Creates trace_id per case
    │     │    │       3. All writes through RunLogger
   ┌▼─────▼────▼───────────────────────────────┐
   │  Per-Run Directory (isolated)              │
   │  events.jsonl   (run execution timeline)   │
   │  calls/         (canonical JSON per call)  │
   │  calls_flat/    (derived text per call)    │
   │  metadata.json  (run identity)             │
   │  metrics.json   (derived at finalize)      │
   │  calls_index.json (derived at finalize)    │
   └────────────────┬──────────────────────────┘
                    │
   ┌────────────────▼──────────────────────────┐
   │  Aggregator                                │
   │  Reads ALL events.jsonl files:             │
   │    experiment-level + per-run              │
   │  Groups by trace_id, case_id, model, cond │
   │  Produces aggregated/ directory            │
   └───────────────────────────────────────────┘
```

### Two logging planes, one logical system

| Plane | Logger | File | Contains |
|-------|--------|------|----------|
| **Control** | OrchestratorLogger | `experiments/{name}/events.jsonl` | Scheduling, preflight, worker lifecycle |
| **Execution** | RunLogger | `experiments/{name}/{model}/{cond}/trial_{n}/events.jsonl` | Run lifecycle, case execution, LLM calls, metrics |

Both planes use the IDENTICAL event schema (Section 5). Both produce events.jsonl files. The aggregator reads ALL of them. Timeline reconstruction merges them by `timestamp` + `event_id` within each file, then by `run_id` across files.

### Stdout

- `sys.stdout.reconfigure(line_buffering=True)` at process start
- All `print()` use `flush=True`
- Every `print()` corresponds to a structured event already written
- No operationally meaningful information exists only in stdout

---

## SECTION 2 — ID System

Four IDs, four roles. No mixing.

| ID | Type | Scope | Purpose | Created by |
|----|------|-------|---------|-----------|
| `run_id` | `str` (UUID-based) | Per (model, condition, trial) | Groups all events in one run | Orchestrator, before submission |
| `trace_id` | `str` (UUID hex) | Per case execution within a run | Groups all events for one case: start, calls, parse, exec, classify, end | RunLogger.start_case() |
| `event_id` | `int` (monotonic) | Per events.jsonl file | Determines replay order within one file | Logger, auto-incremented |
| `call_id` | `int` (monotonic) | Per run | Links events to files in calls/ and calls_flat/ | RunLogger.log_call() |

Rules:
- `event_id` is ordering only. It does NOT identify events across files.
- `trace_id` is the grouping key. Given a trace_id, you get the complete causal chain for one case execution.
- `call_id` is the file linkage key. `call_id=3` → `calls/000003.json` + `calls_flat/000003_generate.txt`.
- `run_id` groups all events and files for one run.

---

## SECTION 3 — Logging API

### BaseLogger (shared by both planes)

```python
class BaseLogger:
    """Shared logic for event writing. Both OrchestratorLogger and RunLogger inherit."""

    def __init__(self, events_path: Path, logger_scope: str):
        # Opens events_path in append mode
        # Initializes event_id counter

    def _write_event(self, event: dict) -> None:
        # Validates event_type and phase
        # Assigns event_id
        # Writes JSON line + flush
        # fsync on critical event types

    def close(self) -> None:
        # Closes file handle
```

### OrchestratorLogger

```python
class OrchestratorLogger(BaseLogger):
    """Control plane logger. Created in orchestrator main process."""

    def __init__(self, experiment_dir: Path):
        super().__init__(experiment_dir / "events.jsonl", "orchestrator")

    def log_event(self, event_type: str, payload: dict) -> int:
        """Write orchestrator-level event. Returns event_id.

        run_id, trace_id, case_id are null for orchestrator events.
        phase is always "orchestrator".
        """
```

### RunLogger

```python
class RunLogger(BaseLogger):
    """Execution plane logger. Created LOCALLY inside each worker process.

    NEVER passed through ProcessPoolExecutor. NEVER pickled.
    """

    def __init__(self, run_dir: Path, run_id: str,
                 model: str, condition: str, trial: int):
        super().__init__(run_dir / "events.jsonl", "run")
        # Creates run_dir, calls/, calls_flat/
        # Writes metadata.json
        # Initializes call_id counter
        # Sets self._current_trace_id = None

    def start_case(self, case_id: str) -> str:
        """Begin a case execution. Creates trace_id. Logs case.start.

        Returns trace_id (UUID hex). All subsequent events until end_case
        are tagged with this trace_id.
        """

    def end_case(self, case_id: str, payload: dict) -> int:
        """End a case execution. Logs case.end. Clears trace_id."""

    def fail_case(self, case_id: str, payload: dict) -> int:
        """Record case failure. Logs case.failed. Clears trace_id."""

    def log_event(self, event_type: str, payload: dict,
                  case_id: str | None = None,
                  phase: str | None = None) -> int:
        """Write run-level event. Injects current trace_id if active."""

    def log_call(self, model: str, prompt: str, response: str,
                 elapsed_seconds: float, case_id: str, phase: str,
                 error: str | None = None,
                 prompt_assembly: dict | None = None) -> int:
        """Log one LLM call. Injects current trace_id.

        Atomically writes:
        1. calls/{call_id:06d}.json (canonical)
        2. calls_flat/{call_id:06d}_{phase}.txt (derived)
        3. events.jsonl entry (timeline)

        Events reference call_id. Events do NOT embed full prompts.
        Full prompt/response lives only in calls/{id}.json.
        """

    def log_metric(self, name: str, value: Any,
                   context: dict | None = None) -> int:
        """Record metric as structured event."""

    def finalize(self) -> dict:
        """Close logger. Derive metrics.json and calls_index.json
        from events.jsonl. Run validation. Return stats."""

    def validate(self) -> tuple[bool, list[str]]:
        """Assert internal consistency."""
```

### Logger creation rules

**Workers create RunLogger locally. OrchestratorLogger exists only in the main process. Neither logger is ever pickled or passed across process boundaries.**

```
CORRECT:
    # Orchestrator (main process)
    orch_logger = OrchestratorLogger(experiment_dir)

    # Worker (child process)
    def run_single(run_dir, run_id, model, condition, trial, config):
        logger = RunLogger(run_dir, run_id, model, condition, trial)

BAD (will break):
    logger = RunLogger(...)
    pool.submit(run_single, logger=logger)
```

---

## SECTION 4 — Event Schema

Every line in every events.jsonl conforms to:

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
  "payload": {
    "call_id": 3,
    "latency_ms": 2341,
    "prompt_length": 1200,
    "response_length": 850,
    "error": null
  }
}
```

For orchestrator events, `run_id`, `trace_id`, `case_id`, `trial`, `model`, `condition` are null. `phase` is `"orchestrator"`.

For run-level events (run.start, run.end), `trace_id` and `case_id` are null.

For case-level and call-level events, `trace_id` is always set (assigned at case.start, cleared at case.end/case.failed).

### VALID_EVENT_TYPES

```python
VALID_EVENT_TYPES = frozenset({
    # Orchestrator lifecycle (control plane)
    "orchestrator.start",
    "orchestrator.schedule",
    "orchestrator.worker_start",
    "orchestrator.worker_end",
    "orchestrator.failure",
    "orchestrator.complete",
    "orchestrator.preflight_pass",
    "orchestrator.preflight_fail",

    # Run lifecycle (execution plane)
    "run.start",
    "run.end",
    "run.failed",

    # Case lifecycle
    "case.start",
    "case.end",
    "case.failed",

    # LLM calls
    "call.generate",
    "call.classifier",
    "call.other",

    # Pipeline stages
    "parse.result",
    "execution.result",

    # Metrics
    "metric.record",

    # Validation
    "validation.preflight_pass",
    "validation.preflight_fail",
    "validation.gate_pass",
    "validation.gate_fail",
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

Both are enforced at write time. Invalid values → `ValueError`.

Phase inference when not provided:
- `orchestrator.*` → `"orchestrator"`
- `run.*` → `"run"`
- `case.*` → `"case"`
- `call.generate` → `"generation"`
- `call.classifier` → `"classification"`
- `parse.*` → `"parsing"`
- `execution.*` → `"evaluation"`
- `metric.*` → `"evaluation"`
- `validation.*` → `"validation"`

---

## SECTION 5 — Event Lifecycle and Boundaries

### Control plane (experiment-level events.jsonl)

```
event_id=1  orchestrator.start       {config_hash, total_work_items, parallelism}
event_id=2  orchestrator.preflight_pass  {check: "validate_cases", cases: 58}
event_id=3  orchestrator.preflight_pass  {check: "evaluator_sanity"}
event_id=4  orchestrator.preflight_pass  {check: "cost_gate", pass_rate: 1.0}
event_id=5  orchestrator.schedule    {run_id: "gpt-5-mini_baseline_t1_abc", model, condition, trial}
event_id=6  orchestrator.schedule    {run_id: "gpt-5-mini_leg_t1_def", ...}
...
event_id=N  orchestrator.worker_start {run_id: "gpt-5-mini_baseline_t1_abc"}
event_id=N+1 orchestrator.worker_end  {run_id: "...", status: "completed", pass_rate: 0.93}
...
event_id=M  orchestrator.complete    {total: 48, completed: 46, failed: 2}
```

### Execution plane (per-run events.jsonl)

```
event_id=1  run.start                  {total_cases: 58, config_hash: "..."}
event_id=2  case.start                 {case_id: "alias_config_a", trace_id: "e7a3b9c2..."}
event_id=3  call.generate              {trace_id: "e7a3b9c2...", call_id: 1, latency_ms: 2341}
event_id=4  parse.result               {trace_id: "e7a3b9c2...", format: "file_dict", error: null}
event_id=5  execution.result           {trace_id: "e7a3b9c2...", pass: true, score: 1.0, ran: true}
event_id=6  call.classifier            {trace_id: "e7a3b9c2...", call_id: 2, latency_ms: 812}
event_id=7  case.end                   {trace_id: "e7a3b9c2...", pass: true, score: 1.0,
                                         code_correct: true, reasoning_correct: true}
event_id=8  case.start                 {case_id: "alias_config_b", trace_id: "f8b4ca..."}
...
event_id=N  run.end                    {pass_rate: 0.931, total_pass: 54, total_cases: 58}
```

### Lifecycle invariants

- Every `case.start` has exactly one matching `case.end` or `case.failed` with same `trace_id`
- `run.start` is always event_id=1 in a run's events.jsonl
- `run.end` or `run.failed` is always the last event
- `call.*`, `parse.*`, `execution.*` events occur only between `case.start` and its end
- All events between `case.start` and `case.end` share the same `trace_id`
- event_ids are strictly monotonically increasing with no gaps within each file

### No-duplication contract

| Fact | Authoritative source | May be echoed? |
|------|---------------------|----------------|
| Preflight result | experiment-level events.jsonl | NOT in run-level logs |
| Worker scheduled/completed/failed | experiment-level events.jsonl | manifest.json caches status |
| Case pass/fail | run-level events.jsonl (case.end) | metrics.json derives from this |
| LLM call details | calls/{id}.json + run events.jsonl (call.*) | calls_flat/ is derived |
| Run-level pass_rate | run events.jsonl (run.end) | manifest may echo for convenience |
| Full experiment status | experiment events.jsonl | manifest is coordination cache |

Authority: experiment events.jsonl for control plane, run events.jsonl for execution plane. If manifest.json or metrics.json disagree, events.jsonl wins.

---

## SECTION 6 — Trace Retrieval Guarantee

Given `trace_id = "e7a3b9c2d1f04567"`, the following MUST be trivially reconstructible from structured logs:

```
Filter events.jsonl where trace_id == "e7a3b9c2d1f04567":

  case.start      → case_id, timestamp
  call.generate   → call_id=1 → calls/000001.json → full agent prompt + response
  parse.result    → parse format, parse error
  execution.result → pass, score, ran, error
  call.classifier → call_id=2 → calls/000002.json → full classifier prompt + response
  case.end        → final pass/fail, score, code_correct, reasoning_correct, failure_type
```

This is the primary debugging primitive. No additional tooling required beyond `grep trace_id events.jsonl` and reading the referenced call files.

Events reference `call_id` for file linkage. Events do NOT embed full prompts or responses — those live only in `calls/{id}.json`.

---

## SECTION 7 — File Layout and Source-of-Truth Rules

```
experiments/
  baseline_vs_leg_v2/
    experiment.yaml                     ← FROZEN CONFIG (written once)
    manifest.json                       ← COORDINATION CACHE (not timeline, not ordered)
    events.jsonl                        ← CONTROL PLANE TIMELINE (orchestrator events)

    gpt-5.4-mini/
      baseline/
        trial_1/
          metadata.json                 ← STATIC (written once at run start)
          events.jsonl                  ← EXECUTION PLANE TIMELINE (authoritative)
          calls/
            000001.json                 ← CANONICAL per-call record
            000002.json
          calls_flat/
            000001_generate.txt         ← DERIVED from calls/000001.json
            000002_classifier.txt
          calls_index.json              ← DERIVED at finalize
          metrics.json                  ← DERIVED from events.jsonl at finalize
        trial_2/
          ...

    aggregated/                         ← DERIVED from all events.jsonl files
      per_model.json
      per_condition.json
      per_trial.json
      per_trace.json
      dashboard.json
```

### Source-of-truth hierarchy

| Artifact | Status | Rule |
|----------|--------|------|
| experiment-level events.jsonl | **AUTHORITATIVE** | Control plane timeline |
| per-run events.jsonl | **AUTHORITATIVE** | Execution plane timeline |
| calls/{id}.json | **CANONICAL** | Authoritative per-call record (superset of call.* payload) |
| metadata.json | STATIC | Written once. Never updated. |
| calls_flat/{id}.txt | DERIVED | From calls/{id}.json. JSON wins on mismatch. |
| calls_index.json | DERIVED | Convenience index from calls/. |
| metrics.json | DERIVED | From events.jsonl at finalize. Never treated as authoritative. Any discrepancy resolved in favor of events.jsonl. |
| manifest.json | COORDINATION CACHE | Orchestrator's status view. NOT a timeline. NOT ordered. NOT authoritative for execution facts. |
| aggregated/*.json | DERIVED | From events.jsonl across runs. |

### Full timeline reconstruction

To reconstruct the complete experiment timeline:

1. Read `experiments/{name}/events.jsonl` — gives control plane (scheduling, preflight, worker lifecycle)
2. For each run referenced in orchestrator.schedule events, read `{run_dir}/events.jsonl` — gives execution plane
3. Order control plane events by their event_id (within file). Order execution plane events by their event_id (within file).
4. Interleave by timestamp for a merged view. Within same timestamp, control plane events (scheduling) precede execution plane events (execution).
5. For call-level detail, dereference `call_id` → `calls/{id}.json`

---

## SECTION 8 — File Write Safety

### events.jsonl (both planes)

- Opened in append text mode (`"a"`, encoding `"utf-8"`) at logger init
- One JSON object per line, terminated by `\n`
- `file.write(json.dumps(event) + "\n")` — one write call per event
- `file.flush()` after every write
- `os.fsync(file.fileno())` after: `run.start`, `run.end`, `run.failed`, `case.failed`, `orchestrator.start`, `orchestrator.complete`, `orchestrator.failure`
- File handle held open for logger lifetime
- Closed in `finalize()` or `close()`

### calls/{id}.json

- Written via temp file → write → flush → fsync → `os.replace(tmp, final)`
- One file per call. Never reopened.

### calls_flat/{id}_{phase}.txt

- Written from same in-memory record as JSON call file
- Same atomic write pattern
- Written in same `log_call()` invocation
- If either write fails, `log_call()` raises `RuntimeError`

### render_call_flat(record) → str

Single function defining flat text format. Located in logging_core.py. No other code formats call logs.

```
=== CALL 000003 ===
MODEL: gpt-5-mini
PHASE: generate
CASE_ID: alias_config_a
CONDITION: baseline
TRIAL: 1
RUN_ID: gpt-5-mini_baseline_t1_a3f8c2d1
TRACE_ID: e7a3b9c2d1f04567
TIMESTAMP: 2026-03-29T10:00:03
LATENCY_MS: 2341

--- PROMPT ---
<full prompt text>

--- RESPONSE ---
<full response text>
```

### Directory creation

- Logger `__init__` creates all required directories with `parents=True, exist_ok=True`
- No directory creation after init

### No cross-process handles

- Each logger created inside its own process
- No file handles cross ProcessPoolExecutor boundary

---

## SECTION 9 — Orchestrator Design

```python
def main():
    sys.stdout.reconfigure(line_buffering=True)

    config = load_experiment_config(args.config)
    validate_config(config)

    experiment_dir = Path(config.output.base_dir) / config.experiment.name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(experiment_dir / "experiment.yaml", config)

    # Orchestrator logger — control plane
    orch_logger = OrchestratorLogger(experiment_dir)
    orch_logger.log_event("orchestrator.start", {
        "config_hash": config.hash,
        "total_models": len(config.models.generation),
        "conditions": config.conditions,
        "trials": config.trials,
    })

    # Preflight — logged at orchestrator level, NOT in workers
    try:
        run_preflight(config)
        orch_logger.log_event("orchestrator.preflight_pass", {"checks": "all"})
    except PreflightError as e:
        orch_logger.log_event("orchestrator.preflight_fail", {"error": str(e)})
        orch_logger.close()
        sys.exit(1)

    # Generate work items
    work_items = generate_work_items(config)
    for item in work_items:
        orch_logger.log_event("orchestrator.schedule", {
            "run_id": item.run_id, "model": item.model,
            "condition": item.condition, "trial": item.trial,
        })

    # Submit — ONLY serializable arguments
    manifest = {}
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

        done = 0
        for future in as_completed(futures):
            item = futures[future]
            done += 1
            try:
                result = future.result()
                orch_logger.log_event("orchestrator.worker_end", {
                    "run_id": item.run_id, "status": "completed",
                    "pass_rate": result.pass_rate,
                })
                manifest[item.run_id] = {"status": "completed", "pass_rate": result.pass_rate}
                print(f"[{done}/{len(work_items)}] {item.run_id} DONE ({result.pass_rate:.1%})", flush=True)
            except Exception as e:
                orch_logger.log_event("orchestrator.failure", {
                    "run_id": item.run_id, "error": str(e),
                })
                manifest[item.run_id] = {"status": "failed", "error": str(e)}
                print(f"[{done}/{len(work_items)}] {item.run_id} FAILED: {e}", flush=True)

    write_json(experiment_dir / "manifest.json", manifest)
    orch_logger.log_event("orchestrator.complete", {
        "total": len(work_items),
        "completed": sum(1 for v in manifest.values() if v["status"] == "completed"),
        "failed": sum(1 for v in manifest.values() if v["status"] == "failed"),
    })
    orch_logger.close()

    # Aggregate
    aggregate_experiment(experiment_dir)
```

---

## SECTION 10 — Worker Execution Model

```python
def run_single(run_dir: str, run_id: str, model: str,
               condition: str, trial: int, config) -> RunResult:

    # Worker creates logger LOCALLY — never passed from orchestrator
    logger = RunLogger(
        run_dir=Path(run_dir), run_id=run_id,
        model=model, condition=condition, trial=trial,
    )

    cases = load_cases(config.cases.source)

    logger.log_event("run.start", {
        "total_cases": len(cases), "config_hash": config.hash,
        "git_hash": get_git_hash(),
    }, phase="run")

    for case in cases:
        case_id = case["id"]

        # Creates trace_id, logs case.start
        trace_id = logger.start_case(case_id)

        try:
            # Generation (LLM call)
            prompt = build_prompt(case, condition)
            raw_output = call_model(prompt, model)
            logger.log_call(model, prompt, raw_output, elapsed,
                           case_id=case_id, phase="generation")

            # Parse
            parsed = parse_response(raw_output, case)
            logger.log_event("parse.result", {
                "format": parsed.get("response_format"),
                "error": parsed.get("parse_error"),
            }, case_id=case_id, phase="parsing")

            # Reconstruct + Execute
            code = reconstruct(parsed, case)
            exec_result = exec_evaluate(case, code)
            logger.log_event("execution.result", {
                "pass": exec_result["pass"],
                "score": exec_result["score"],
                "ran": exec_result["execution"]["ran"],
            }, case_id=case_id, phase="evaluation")

            # Classify reasoning (LLM call)
            classify = llm_classify(case, code, parsed["reasoning"])
            logger.log_call(config.models.evaluator.name,
                           classify_prompt, classify_response, elapsed,
                           case_id=case_id, phase="classification")

            # End case
            logger.end_case(case_id, {
                "pass": exec_result["pass"],
                "score": exec_result["score"],
                "code_correct": exec_result["pass"],
                "reasoning_correct": classify.get("reasoning_correct"),
                "failure_type": classify.get("failure_type"),
            })

        except Exception as e:
            logger.fail_case(case_id, {"error": f"{type(e).__name__}: {e}"})

    stats = logger.finalize()
    return RunResult(pass_rate=stats["pass_rate"], stats=stats)
```

### trace_id flow

1. `logger.start_case("alias_config_a")` → creates `trace_id = uuid4().hex`, stores as `self._current_trace_id`, logs `case.start` with trace_id
2. All subsequent `log_event()` and `log_call()` within this case automatically inject `self._current_trace_id`
3. `logger.end_case()` or `logger.fail_case()` logs the terminal event with trace_id, then sets `self._current_trace_id = None`
4. If `log_call()` or `log_event()` is called with `self._current_trace_id = None`, trace_id in the event is null (for run-level events)

---

## SECTION 11 — Aggregator Design

### What it reads

The aggregator reads the FULL structured event stream from:
- `experiments/{name}/events.jsonl` (control plane)
- `experiments/{name}/{model}/{cond}/trial_{n}/events.jsonl` (all execution planes)

### Grouping keys

| Group by | Yields |
|----------|--------|
| `trace_id` | Complete causal trace for one case execution |
| `case_id` | All executions of one case across trials/models |
| `model` | All events for one model |
| `condition` | All events for one condition |
| `model + condition` | Per-cell in the experiment matrix |
| `model + condition + trial` | One specific run |

### Metrics computed

From `case.end` / `case.failed`:
- Pass rate, failure rate, score distribution
- Failure type distribution
- Per-case stability across trials

From `call.generate` / `call.classifier`:
- Average latency by phase and model
- API error rate and timeout frequency
- Total calls by model and phase
- Parse failure rate (from `parse.result` events)

From `execution.result`:
- ran_rate (code actually executed)
- Assembly error rate

From trace-level grouping:
- LEG analysis (reasoning_correct vs code_correct per trace)
- Cases where generation succeeded but classification failed
- Cases where parse failed but execution was attempted

### What it writes

- `aggregated/per_model.json`
- `aggregated/per_condition.json`
- `aggregated/per_trial.json`
- `aggregated/per_trace.json` (optional: trace-level summary for debugging)
- `aggregated/dashboard.json`

---

## SECTION 12 — Validation Guarantees

### RunLogger.finalize()

1. events.jsonl exists and has at least 2 events (run.start + run.end)
2. `len(calls/*.json) == len(calls_flat/*.txt)`
3. Every `call.*` event references a `call_id` with matching file in `calls/`
4. Every `case.start` has exactly one matching `case.end` or `case.failed` with same trace_id
5. All events between case.start and case.end share the same trace_id
6. `run.start` is event_id=1, `run.end` or `run.failed` is last event
7. event_ids strictly monotonically increasing, no gaps
8. No file named `calls_flat.txt` exists
9. metrics.json was derived from events.jsonl (not independently written)

### OrchestratorLogger.close()

1. events.jsonl exists
2. orchestrator.start is event_id=1
3. orchestrator.complete or orchestrator.failure is last event
4. Every orchestrator.schedule has at most one orchestrator.worker_end or orchestrator.failure with same run_id

Any validation failure → `RuntimeError`.

---

## SECTION 13 — Migration Plan

### Step 0: Convert existing logs
- `scripts/migrate_call_logs.py` converts existing `calls/` JSON to `calls_flat/` text
- Deletes `calls_flat.txt`
- Idempotent

### Step 1: Implement logging_core.py
- `BaseLogger`, `OrchestratorLogger`, `RunLogger`
- `render_call_flat()`
- Event schema with event_id + trace_id
- VALID_EVENT_TYPES, VALID_PHASES enforcement
- Write safety (flush, fsync on critical events, atomic call writes)
- finalize() with validation
- Replaces `call_logger.py`

### Step 2: Implement orchestrate.py
- Config loading + validation
- Preflight (logged via OrchestratorLogger)
- Work item generation
- ProcessPoolExecutor — workers get serializable args only
- OrchestratorLogger for control plane
- manifest.json as coordination cache
- Progress lines paired with structured events

### Step 3: Wire workers to RunLogger
- Workers create RunLogger locally
- start_case/end_case/fail_case manage trace_id
- log_call replaces call_logger.emit_call
- log_event replaces live_metrics.emit_event
- Remove all manual file appends from execution.py, runner.py

### Step 4: Implement aggregate.py
- Reads all events.jsonl files (experiment-level + per-run)
- Groups by trace_id, case_id, model, condition
- Computes full metric set (pass rate, latency, parse failures, LEG)
- Writes aggregated/*.json

### Step 5: Delete legacy
- `call_logger.py`
- `live_metrics.py:emit_event`
- `scripts/run_ablation_leg_8t.sh`
- `scripts/update_dashboards.py`
- `scripts/validate_smoke.py`
- All `calls_flat.txt` references

### Step 6: Update Makefile
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

1. `python orchestrate.py --config experiment.yaml` runs the full experiment
2. ALL logging flows through `logging_core.BaseLogger` subclasses
3. Control plane: experiment-level events.jsonl records scheduling, preflight, worker lifecycle
4. Execution plane: per-run events.jsonl records case execution, calls, results
5. Both planes use identical schema with event_id, timestamp, trace_id
6. Every case execution has a unique trace_id grouping all its events
7. Given any trace_id, full causal chain is reconstructible: prompt → response → parse → execution → classification → result
8. Workers create loggers locally — nothing pickled across process boundaries
9. Preflight is logged at orchestrator level only
10. manifest.json is coordination cache, never execution truth
11. metrics.json and calls_index.json are derived from events.jsonl, never independent
12. `len(calls/*.json) == len(calls_flat/*.txt)` validated at run end
13. No `calls_flat.txt` anywhere
14. No information exists only in stdout
15. Aggregator consumes full event stream, supports trace-level analysis
16. Same config + same code = same experiment
17. No bash scripts
