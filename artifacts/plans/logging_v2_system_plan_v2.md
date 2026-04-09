Date: 2026-04-10
Time: 02:00

# LOGGING V2 SYSTEM PLAN v2

---

# 1. EXECUTIVE SUMMARY

Complete replacement for the logging and run-artifact system. WAL and call artifacts are the two canonical objects. Everything else is derived. All semantic values are typed enums. All paths are built from a single centralized axis system. All event types, emitters, statuses, views, and stats are registry-driven with compile-time-safe enum keys. No raw strings in control flow. No global mutable state. No ambiguity.

---

# 2. CURRENT-SYSTEM RISKS BEING ELIMINATED

| Risk | Elimination |
|------|------------|
| Run directory reuse after crash | Epoch-ms + atomic mkdir. No `exist_ok`. |
| Global mutable logger state | WALWriter is stateless, passed via ExecutionContext. No module-level globals. |
| Dual event schema (legacy + canonical + payload) | One schema. One enum-typed vocabulary. |
| Manual parent ID threading | Engine and controller auto-thread parent chains. |
| No graph engine WAL | Engine emits typed WAL events. |
| Parallel logging paths (call_logger + RunLogger) | One call artifact writer. One WAL writer. |
| Hardcoded strings scattered across modules | All semantic values are enums from `core/logging_v2/enums.py`. |
| No experiment stamp in run dir | Dir name contains experiment name + git SHA + epoch-ms. |
| Non-configurable stats | Registry-driven stats keyed by `StatName` enum. |

---

# 3. CANONICAL CONCEPTS AND TERMINOLOGY

| Term | Definition | Ownership |
|------|-----------|-----------|
| condition | Experimental condition. First-class axis. | Config YAML `conditions` section. Validated at startup. |
| model | LLM model identity. First-class axis. | Config YAML `models` section. Normalized at startup. |
| case | Semantic case identifier. First-class axis. | `cases_v2.json`. Validated filesystem-safe at startup. |
| trial | Zero-indexed attempt index. Always `>= 0`. | Fixed. Zero-indexed everywhere. No exceptions. |
| path | Execution flow within a trial. `0` today. | Fixed. Zero-indexed. |
| node | Graph node identity. | `control/registry.py`. Validated unique and filesystem-safe at startup. |
| call | Single LLM/API invocation. Sequentially numbered per (trial, path, node). | Fixed. One-indexed (`call_001`, `call_002`). |
| WAL | Write-ahead log. `wal.jsonl`. Canonical truth. | `core/logging_v2/wal_writer.py` |
| call artifact | `.json` (canonical) + `.txt` (derived) per call. | `core/logging_v2/call_artifacts.py` |
| materialized view | Derived rendering. NOT canonical. | `core/logging_v2/views/` |
| manifest | Run-root metadata. | `core/logging_v2/manifest.py` |

---

# 4. ENUM DEFINITIONS

**File:** `core/logging_v2/enums.py`

All enums are `str` enums for JSON serialization. All control flow uses enum members, never raw strings.

```python
class EventType(str, Enum):
    # Run lifecycle
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    # Case lifecycle
    CASE_STARTED = "case.started"
    CASE_COMPLETED = "case.completed"
    CASE_FAILED = "case.failed"
    # Engine lifecycle
    ENGINE_GRAPH_STARTED = "engine.graph.started"
    ENGINE_GRAPH_COMPLETED = "engine.graph.completed"
    ENGINE_GRAPH_FAILED = "engine.graph.failed"
    ENGINE_NODE_STARTED = "engine.node.started"
    ENGINE_NODE_COMPLETED = "engine.node.completed"
    ENGINE_NODE_FAILED = "engine.node.failed"
    ENGINE_NODE_SKIPPED = "engine.node.skipped"
    ENGINE_MERGE_COMPLETED = "engine.merge.completed"
    # Controller lifecycle
    CONTROLLER_ATTEMPT_STARTED = "controller.attempt.started"
    CONTROLLER_ATTEMPT_COMPLETED = "controller.attempt.completed"
    CONTROLLER_RETRY_DECIDED = "controller.retry.decided"
    CONTROLLER_CRITIQUE_GENERATED = "controller.critique.generated"
    CONTROLLER_RESULT_SELECTED = "controller.result.selected"
    # LLM calls
    LLM_CALL_STARTED = "llm.call.started"
    LLM_CALL_COMPLETED = "llm.call.completed"
    LLM_CALL_FAILED = "llm.call.failed"
    # Node results
    NODE_RESULT_PRODUCED = "node.result.produced"

class Emitter(str, Enum):
    ENGINE = "engine"
    CONTROLLER = "controller"
    RUNNER = "runner"
    NODE = "node"

class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CRASHED = "crashed"

class CallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"

class Axis(str, Enum):
    CONDITION = "condition"
    MODEL = "model"
    CASE = "case"
    TRIAL = "trial"
    PATH = "path"
    NODE = "node"
    CALL = "call"

class RedisWriteMode(str, Enum):
    SYNC = "sync"
    ASYNC_BUFFERED = "async_buffered"

class RedisFailureMode(str, Enum):
    LOG_AND_CONTINUE = "log_and_continue"
    RAISE = "raise"

class ViewName(str, Enum):
    SUMMARY = "summary"
    TIMELINE = "timeline"
    FAILURES = "failures"
    LLM_CALLS = "llm_calls"
    TRIAL_TABLE = "trial_table"
    INDEX = "index"
    CASE_DETAIL = "case_detail"

class StatName(str, Enum):
    PASS_RATE = "pass_rate"
    LEG_RATE = "leg_rate"
    ATTEMPT_COUNT = "attempt_count"
    PARSE_SUCCESS_RATE = "parse_success_rate"
    MEAN_LATENCY_MS = "mean_latency_ms"
```

**Import pattern:** Every module imports from `core.logging_v2.enums`. No module defines its own semantic string constants for these concepts.

**Validation:** `validate_event()` checks `event.event_type` is a member of `EventType`. `validate_manifest()` checks `manifest.status` is a member of `RunStatus`. Type checkers enforce enum usage at call sites.

---

# 5. AXIS SYSTEM

**File:** `core/logging_v2/axes.py`

```python
@dataclass(frozen=True)
class AxisSpec:
    axis: Axis
    prefix: str | None      # None = use raw value, "trial_" = prefix value
    required: bool           # True = must be present in path build
    zero_indexed: bool       # True = value must be int >= 0

AXIS_ORDER: tuple[Axis, ...] = (
    Axis.CONDITION,
    Axis.MODEL,
    Axis.CASE,
    Axis.TRIAL,
    Axis.PATH,
    Axis.NODE,
    Axis.CALL,
)

AXIS_SPECS: dict[Axis, AxisSpec] = {
    Axis.CONDITION: AxisSpec(axis=Axis.CONDITION, prefix=None, required=True, zero_indexed=False),
    Axis.MODEL:     AxisSpec(axis=Axis.MODEL,     prefix=None, required=True, zero_indexed=False),
    Axis.CASE:      AxisSpec(axis=Axis.CASE,      prefix=None, required=True, zero_indexed=False),
    Axis.TRIAL:     AxisSpec(axis=Axis.TRIAL,      prefix="trial_", required=True, zero_indexed=True),
    Axis.PATH:      AxisSpec(axis=Axis.PATH,       prefix="path_",  required=True, zero_indexed=True),
    Axis.NODE:      AxisSpec(axis=Axis.NODE,       prefix=None, required=False, zero_indexed=False),
    Axis.CALL:      AxisSpec(axis=Axis.CALL,       prefix="call_",  required=False, zero_indexed=False),
}
```

**Rules:**
- `AXIS_ORDER` is the single source of truth for directory nesting order
- Every path builder iterates `AXIS_ORDER` and applies `AXIS_SPECS`
- `prefix` is applied as `f"{spec.prefix}{value}"` when non-None
- `zero_indexed=True` enforces `isinstance(value, int) and value >= 0`
- `required=True` means the axis must appear in the `axes` dict for that artifact type

---

# 6. PATH BUILDING

**File:** `core/logging_v2/paths.py`

**Single function. All artifact paths go through this. No exceptions.**

```python
def build_artifact_path(
    run_root: Path,
    artifact_group: str,       # "calls" | "execution" | "diffs"
    axes: dict[Axis, Any],
    leaf: str | None = None,
) -> Path:
```

**Implementation rules:**
- Iterates `AXIS_ORDER`
- For each axis in order: if present in `axes`, appends `spec.prefix + str(value)` or `str(value)` to path
- If `spec.zero_indexed` and value is int: validates `value >= 0`, raises `ValueError` otherwise
- If `spec.required` and axis not in `axes`: raises `ValueError`
- All string values validated filesystem-safe: no `/`, `\`, `:`, `..`, NUL
- `leaf` appended last if non-None
- Returns `run_root / artifact_group / ... / leaf`

**Forbidden:** Any other module constructing paths by string concatenation, f-strings, or manual `/` joining for artifact directories.

---

# 7. RUN DIRECTORY NAMING

**Format:**
```
{YYYY-MM-DD}_{HH-MM-SS}-{epoch_ms}-{git_sha_prefix}_{experiment_name}
```

**Example:**
```
2026-04-09_23-30-12-1712705412483-a1b2c3_ablation_ddc_4omini
```

**Rules:**
- UTC wall clock for human-readable portion
- `epoch_ms` = `int(time.time() * 1000)`
- `git_sha_prefix` = first 6 chars of `git rev-parse HEAD`, or `nogit` if not a git repo
- `experiment_name` = `config.experiment.name` with `[^a-zA-Z0-9_-]` replaced by `_`
- One underscore before experiment_name
- `os.mkdir(target_path)` — no `exist_ok`. Collision raises `FileExistsError`.
- On collision: sleep 2ms, recompute epoch_ms, retry once. Second collision: raise `RuntimeError`.

**Location:** `logs_v2/{run_dir_name}/`

**Owner:** `core/logging_v2/run_dir.py:create_run_directory(base_dir: Path, config) -> Path`

---

# 8. INSIDE-RUN DIRECTORY STRUCTURE

```
logs_v2/{run_dir_name}/
  manifest.json
  wal.jsonl
  artifacts/
    calls/
      {condition}/{model}/{case}/trial_{i}/path_{j}/{node}/
        call_001.json
        call_001.txt
    execution/
      {condition}/{model}/{case}/trial_{i}/path_{j}/
        result.json
        stdout.txt
        stderr.txt
    diffs/
      {condition}/{model}/{case}/trial_{i}/
        path_{j}.diff
  materialized_views/
    summary.md
    timeline.md
    failures.md
    llm_calls.md
    trial_table.md
    index.json
    cases/
      {case_id}.md
```

---

# 9. MANIFEST SCHEMA

**File:** `manifest.json` at run root.

**Owner:** `core/logging_v2/manifest.py`

```python
@dataclass
class RunManifest:
    # Identity (immutable)
    run_id: str                    # UUID hex
    run_dir_name: str
    experiment_name: str
    experiment_description: str
    experiment_tags: list[str]
    seed: int
    config_path: str
    config_hash: str               # SHA256 of config file bytes

    # Git (immutable)
    git_commit_sha: str            # full 40-char
    git_short_sha: str             # 6-char used in dir name
    git_branch: str
    git_dirty: bool

    # Timestamps
    start_timestamp: str           # ISO 8601 UTC
    end_timestamp: str | None      # set on terminal status

    # Status (mutable, monotonic transitions only)
    status: RunStatus              # PENDING → RUNNING → COMPLETED|FAILED|CRASHED

    # Models (immutable)
    models: list[dict]             # [{name, temperature, max_tokens, top_p, role}]

    # Parallelism (immutable)
    num_workers: int
    worker_timeout_seconds: int

    # Logging (immutable)
    logging_schema_version: str    # "2.0"
    redis_enabled: bool
    redis_stream_name: str | None
    redis_url: str | None

    # Paths (immutable, relative to run root)
    wal_path: str                  # "wal.jsonl"
    artifacts_path: str            # "artifacts/"
    materialized_views_path: str   # "materialized_views/"

    # Environment (immutable)
    python_version: str
    hostname: str
    platform: str
```

**Status transitions (enforced in code):**

```python
ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING:   frozenset({RunStatus.RUNNING}),
    RunStatus.RUNNING:   frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CRASHED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED:    frozenset(),
    RunStatus.CRASHED:   frozenset(),
}

def transition_status(current: RunStatus, next_status: RunStatus) -> None:
    if next_status not in ALLOWED_TRANSITIONS[current]:
        raise RuntimeError(
            f"Invalid manifest status transition: {current.value} → {next_status.value}. "
            f"Allowed: {sorted(s.value for s in ALLOWED_TRANSITIONS[current])}"
        )
```

---

# 10. LOGGING CONFIGURATION

**File:** `core/logging_v2/config.py`

```python
@dataclass(frozen=True)
class LoggingV2Config:
    schema_version: str = "2.0"
    wal_filename: str = "wal.jsonl"
    artifacts_dirname: str = "artifacts"
    materialized_views_dirname: str = "materialized_views"

    # Call text format (fixed section ordering: METADATA → REQUEST → RESPONSE)
    call_txt_separator: str = "=" * 80
    call_txt_section_names: tuple[str, str, str] = ("METADATA", "REQUEST", "RESPONSE")

    # Redis
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "t3_events"
    redis_write_mode: RedisWriteMode = RedisWriteMode.ASYNC_BUFFERED
    redis_failure_mode: RedisFailureMode = RedisFailureMode.LOG_AND_CONTINUE
```

**Validation:** `core/logging_v2/config.py:validate_config(config: LoggingV2Config) -> None`
- `schema_version == "2.0"`
- `redis_write_mode` is member of `RedisWriteMode`
- `redis_failure_mode` is member of `RedisFailureMode`
- `len(call_txt_section_names) == 3`
- `call_txt_separator` is non-empty

---

# 11. WAL EVENT SCHEMA

**File:** `core/logging_v2/events.py`

```python
@dataclass(frozen=True)
class WALEvent:
    event_id: str               # "{seq:08d}"
    event_type: EventType       # enum member
    schema_version: str         # "2.0"
    timestamp: str              # ISO 8601 UTC
    seq: int                    # monotonic append order

    # Lineage
    run_id: str
    case_id: str | None
    condition: str | None
    model: str | None
    trial: int | None           # >= 0
    path: int | None            # >= 0
    node: str | None

    # Causality
    parent_event_id: str | None
    trace_id: str | None

    # Ownership
    emitter: Emitter            # enum member

    # Payload
    payload: dict

    # Call artifact reference (for LLM_CALL_COMPLETED only)
    call_id: str | None = None
    artifact_ref: str | None = None
```

**Event type registry:** `core/logging_v2/event_types.py`

```python
@dataclass(frozen=True)
class EventTypeSpec:
    event_type: EventType
    emitter: Emitter
    requires_case: bool
    requires_call_id: bool

EVENT_TYPE_SPECS: dict[EventType, EventTypeSpec] = {
    EventType.RUN_STARTED: EventTypeSpec(EventType.RUN_STARTED, Emitter.RUNNER, requires_case=False, requires_call_id=False),
    EventType.RUN_COMPLETED: EventTypeSpec(EventType.RUN_COMPLETED, Emitter.RUNNER, requires_case=False, requires_call_id=False),
    EventType.RUN_FAILED: EventTypeSpec(EventType.RUN_FAILED, Emitter.RUNNER, requires_case=False, requires_call_id=False),
    EventType.CASE_STARTED: EventTypeSpec(EventType.CASE_STARTED, Emitter.RUNNER, requires_case=True, requires_call_id=False),
    EventType.CASE_COMPLETED: EventTypeSpec(EventType.CASE_COMPLETED, Emitter.RUNNER, requires_case=True, requires_call_id=False),
    EventType.CASE_FAILED: EventTypeSpec(EventType.CASE_FAILED, Emitter.RUNNER, requires_case=True, requires_call_id=False),
    EventType.ENGINE_GRAPH_STARTED: EventTypeSpec(EventType.ENGINE_GRAPH_STARTED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_GRAPH_COMPLETED: EventTypeSpec(EventType.ENGINE_GRAPH_COMPLETED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_GRAPH_FAILED: EventTypeSpec(EventType.ENGINE_GRAPH_FAILED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_NODE_STARTED: EventTypeSpec(EventType.ENGINE_NODE_STARTED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_NODE_COMPLETED: EventTypeSpec(EventType.ENGINE_NODE_COMPLETED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_NODE_FAILED: EventTypeSpec(EventType.ENGINE_NODE_FAILED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_NODE_SKIPPED: EventTypeSpec(EventType.ENGINE_NODE_SKIPPED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.ENGINE_MERGE_COMPLETED: EventTypeSpec(EventType.ENGINE_MERGE_COMPLETED, Emitter.ENGINE, requires_case=True, requires_call_id=False),
    EventType.CONTROLLER_ATTEMPT_STARTED: EventTypeSpec(EventType.CONTROLLER_ATTEMPT_STARTED, Emitter.CONTROLLER, requires_case=True, requires_call_id=False),
    EventType.CONTROLLER_ATTEMPT_COMPLETED: EventTypeSpec(EventType.CONTROLLER_ATTEMPT_COMPLETED, Emitter.CONTROLLER, requires_case=True, requires_call_id=False),
    EventType.CONTROLLER_RETRY_DECIDED: EventTypeSpec(EventType.CONTROLLER_RETRY_DECIDED, Emitter.CONTROLLER, requires_case=True, requires_call_id=False),
    EventType.CONTROLLER_CRITIQUE_GENERATED: EventTypeSpec(EventType.CONTROLLER_CRITIQUE_GENERATED, Emitter.CONTROLLER, requires_case=True, requires_call_id=False),
    EventType.CONTROLLER_RESULT_SELECTED: EventTypeSpec(EventType.CONTROLLER_RESULT_SELECTED, Emitter.CONTROLLER, requires_case=True, requires_call_id=False),
    EventType.LLM_CALL_STARTED: EventTypeSpec(EventType.LLM_CALL_STARTED, Emitter.NODE, requires_case=True, requires_call_id=True),
    EventType.LLM_CALL_COMPLETED: EventTypeSpec(EventType.LLM_CALL_COMPLETED, Emitter.NODE, requires_case=True, requires_call_id=True),
    EventType.LLM_CALL_FAILED: EventTypeSpec(EventType.LLM_CALL_FAILED, Emitter.NODE, requires_case=True, requires_call_id=True),
    EventType.NODE_RESULT_PRODUCED: EventTypeSpec(EventType.NODE_RESULT_PRODUCED, Emitter.NODE, requires_case=True, requires_call_id=False),
}
```

**Validation:** `core/logging_v2/events.py:validate_event(event: WALEvent) -> None`
- `event.event_type` is member of `EventType` (type-checked at construction)
- `event.emitter` matches `EVENT_TYPE_SPECS[event.event_type].emitter`
- `event.case_id` is non-None when `requires_case` is True
- `event.call_id` is non-None when `requires_call_id` is True
- `event.trial` is None or `>= 0`
- `event.path` is None or `>= 0`
- `event.seq` is > 0
- `event.schema_version == "2.0"`
- If `event.artifact_ref` is non-None: must be a relative path (no absolute paths)

**Axis consistency validation:** `core/logging_v2/events.py:validate_axis_consistency(event: WALEvent) -> None`
- If `event.node` is not None: `event.trial` and `event.path` must be not None
- If `event.event_type` in `{LLM_CALL_STARTED, LLM_CALL_COMPLETED, LLM_CALL_FAILED}`: all of `case_id`, `condition`, `model`, `trial`, `path`, `node` must be non-None

---

# 12. CALL ARTIFACT SCHEMAS

**Machine-readable: `call_{k:03d}.json`**

```python
@dataclass
class CallArtifact:
    call_id: str                # "{seq:08d}" matching WAL event
    event_id: str               # WAL event_id referencing this artifact
    timestamp: str              # ISO 8601 UTC
    model: str
    node: str
    phase: str                  # "generation" | "classification" | "oracle" | "critique"
    run_id: str
    case_id: str
    condition: str
    trial: int                  # zero-indexed
    path: int                   # zero-indexed
    prompt: str                 # FULL text
    prompt_hash: str            # SHA256
    prompt_length: int
    temperature: float
    top_p: float
    max_tokens: int | None
    response: str               # FULL text
    response_hash: str          # SHA256
    response_length: int
    latency_ms: int
    status: CallStatus          # enum
    error: str | None
```

**Human-readable: `call_{k:03d}.txt`**

Rendered by `core/logging_v2/call_artifacts.py:render_call_txt(call: CallArtifact, config: LoggingV2Config) -> str`

**Fixed section ordering: METADATA → REQUEST → RESPONSE. No conditional sections. No dynamic headers.**

```
================================================================================
 METADATA
================================================================================
model:     gpt-4o-mini
node:      generate
phase:     generation
case:      alias_config_c
condition: baseline_v3
trial:     0
path:      0
call:      1
latency:   1423ms
status:    success

================================================================================
 REQUEST
================================================================================
{full prompt text}

================================================================================
 RESPONSE
================================================================================
{full response text}
```

Section headers: `config.call_txt_separator + "\n " + config.call_txt_section_names[i] + "\n" + config.call_txt_separator`

**Write ordering (non-negotiable):**
1. Write `call_{k:03d}.json` atomically (temp + fsync + rename)
2. Emit `LLM_CALL_COMPLETED` WAL event with `artifact_ref` pointing to the .json file
3. Write `call_{k:03d}.txt` atomically (temp + fsync + rename) — secondary, non-canonical

WAL never references a file that does not yet exist on disk.

---

# 13. WAL WRITER

**File:** `core/logging_v2/wal_writer.py`

```python
class WALWriter:
    def __init__(self, wal_path: Path, run_id: str, sinks: list[Sink] | None = None) -> None:
        self.wal_path = wal_path
        self.run_id = run_id
        self.sinks = sinks or []
        self.seq = 0
        self.file = open(wal_path, "a", encoding="utf-8")

    def emit(self, event: WALEvent) -> str:
        validate_event(event)
        validate_axis_consistency(event)
        self.seq += 1
        # seq assigned by writer, not caller
        record = asdict(event)
        record["seq"] = self.seq
        record["event_id"] = f"{self.seq:08d}"
        line = json.dumps(record, default=str) + "\n"
        self.file.write(line)
        self.file.flush()
        os.fsync(self.file.fileno())
        # Emit to sinks (non-blocking, never blocks WAL)
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:
                pass  # sinks must not block WAL
        return record["event_id"]

    def close(self) -> None:
        self.file.close()
        for sink in self.sinks:
            sink.close()
```

**Properties:** No trace state. No trajectory state. No accumulated metrics. Stateless except for `seq` counter and file handle.

---

# 14. SINK PROTOCOL

**File:** `core/logging_v2/sinks.py`

```python
class Sink(Protocol):
    def emit(self, event: WALEvent) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

WALWriter owns `self.sinks: list[Sink]`. WAL file write always succeeds first. Sink failures are caught and logged. Sink failures never block WAL writes. Sink failures never raise to callers.

---

# 15. REDIS SINK

**File:** `core/logging_v2/redis_sink.py`

```python
class RedisSink:
    def __init__(self, config: LoggingV2Config) -> None: ...
    def emit(self, event: WALEvent) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

- Mirrors WAL events serialized to JSON
- Stream name from `config.redis_stream_name`
- Write mode from `config.redis_write_mode`: `ASYNC_BUFFERED` queues and flushes in batches; `SYNC` writes per event
- Failure mode from `config.redis_failure_mode`: `LOG_AND_CONTINUE` logs warning; `RAISE` propagates (but this is caught by WALWriter's sink loop, so it still does not block WAL)
- Instantiated only if `config.redis_enabled`
- Redis is NOT canonical truth. Consumers can rebuild from WAL if events are missed.

---

# 16. MATERIALIZED VIEWS

**Directory:** `materialized_views/` at run root.

**File:** `core/logging_v2/views/registry.py`

```python
@dataclass(frozen=True)
class ViewSpec:
    name: ViewName
    filename: str
    renderer: Callable[[RunIR, LoggingV2Config], str]

VIEW_REGISTRY: dict[ViewName, ViewSpec] = {
    ViewName.SUMMARY:     ViewSpec(ViewName.SUMMARY,     "summary.md",     render_summary),
    ViewName.TIMELINE:    ViewSpec(ViewName.TIMELINE,     "timeline.md",    render_timeline),
    ViewName.FAILURES:    ViewSpec(ViewName.FAILURES,     "failures.md",    render_failures),
    ViewName.LLM_CALLS:   ViewSpec(ViewName.LLM_CALLS,   "llm_calls.md",   render_llm_calls),
    ViewName.TRIAL_TABLE: ViewSpec(ViewName.TRIAL_TABLE, "trial_table.md", render_trial_table),
    ViewName.INDEX:       ViewSpec(ViewName.INDEX,       "index.json",     render_index),
}
```

**Intermediate representation:** `core/logging_v2/views/intermediate.py`

```python
@dataclass
class RunIR:
    manifest: RunManifest
    events: list[WALEvent]
    calls: list[CallArtifact]
    events_by_case: dict[str, list[WALEvent]]
    events_by_type: dict[EventType, list[WALEvent]]
    calls_by_case: dict[str, list[CallArtifact]]
    calls_by_node: dict[str, list[CallArtifact]]
```

`build_ir(run_root: Path) -> RunIR` reads WAL + call artifacts only. No runtime state.

**Renderers are pure functions.** Signature: `render_X(ir: RunIR, config: LoggingV2Config) -> str`. No filesystem access. No side effects. No runtime state.

**Rebuild:** `core/logging_v2/views/rebuild.py:rebuild_views(run_root: Path, config: LoggingV2Config) -> None`
- Calls `build_ir(run_root)`
- Iterates `VIEW_REGISTRY`
- Writes each view atomically to `materialized_views/`
- Generates `cases/{case_id}.md` for each case in IR

---

# 17. STATISTICS / AGGREGATION

**File:** `core/logging_v2/stats/registry.py`

```python
@dataclass(frozen=True)
class StatSpec:
    name: StatName
    compute: Callable[[RunIR, list[Axis]], dict]
    axes: list[Axis]

STAT_REGISTRY: dict[StatName, StatSpec] = {
    StatName.PASS_RATE:          StatSpec(StatName.PASS_RATE,          compute_pass_rate,         [Axis.CONDITION, Axis.MODEL]),
    StatName.LEG_RATE:           StatSpec(StatName.LEG_RATE,           compute_leg_rate,          [Axis.CONDITION, Axis.MODEL]),
    StatName.ATTEMPT_COUNT:      StatSpec(StatName.ATTEMPT_COUNT,      compute_attempt_count,     [Axis.CONDITION, Axis.MODEL, Axis.CASE]),
    StatName.PARSE_SUCCESS_RATE: StatSpec(StatName.PARSE_SUCCESS_RATE, compute_parse_rate,        [Axis.CONDITION, Axis.MODEL]),
    StatName.MEAN_LATENCY_MS:    StatSpec(StatName.MEAN_LATENCY_MS,    compute_mean_latency,      [Axis.CONDITION, Axis.MODEL, Axis.NODE]),
}
```

Adding a stat: one entry in `STAT_REGISTRY` with a `StatName` enum member. Summary view auto-includes all registered stats. No other code changes.

---

# 18. VALIDATION RULES AND STARTUP CHECKS

**File:** `core/logging_v2/validation.py`

Executed BEFORE run directory creation. All checks must pass or the run does not start.

| Check | Validation | Failure |
|-------|-----------|---------|
| Node name uniqueness | All IDs in `control/registry.py` are unique | `RuntimeError` |
| Node names filesystem-safe | No `/`, `\`, `:`, `..`, NUL | `RuntimeError` |
| Condition names filesystem-safe | Same rules | `RuntimeError` |
| Model names normalized | All model names in config match exactly (no aliases) | `RuntimeError` |
| Case IDs filesystem-safe | No path separators | `RuntimeError` |
| Config hash | SHA256 of config file content | Stored in manifest |
| Git SHA | `git rev-parse HEAD` succeeds or returns `"nogit"` | Warning only |
| Target run directory absent | `os.path.exists(target)` returns False | `RuntimeError` |
| Redis reachable (if enabled) | Ping | Warning (`LOG_AND_CONTINUE`) or `RuntimeError` (`RAISE`) |
| Trial zero-indexing | All trial values in config are integers >= 0 | `RuntimeError` |

---

# 19. WRITE ORDERING / ATOMICITY / CRASH SEMANTICS

**Run creation:**
1. Compute run directory name (epoch_ms + git SHA + experiment name)
2. `os.mkdir(run_dir)` — fails on collision
3. Write `manifest.json` atomically with `status: PENDING`
4. Open `wal.jsonl` for append
5. Emit `RUN_STARTED` event
6. Update manifest to `status: RUNNING`

**Crash semantics:**
- Incomplete: manifest stays at `RUNNING`, no `end_timestamp`
- WAL may be truncated mid-line: readers skip malformed trailing lines
- Call .json artifacts are atomic (temp + fsync + rename): either complete or absent
- .txt artifacts may be absent if crash occurs after step 2 of call write but before step 3
- Materialized views may be stale: rebuild from WAL + artifacts
- No run directory is ever reused or overwritten

---

# 20. MAPPING FROM EXISTING SYSTEM

| Old | New | Action |
|-----|-----|--------|
| `logging_core.py:RunLogger` | `wal_writer.py:WALWriter` | New stateless writer |
| `logging_core.py:OrchestratorLogger` | `wal_writer.py:WALWriter` (separate instance) | Unified |
| `call_logger.py` | `call_artifacts.py` | New. Global state eliminated. |
| `prompt_store.py` | Absorbed into `call_artifacts.py` | Prompt in call .txt/.json |
| `v2_metrics.py` | `stats/` | Registry-driven |
| `v2_dashboard.py` | `views/` | Registry-driven |
| `live_metrics.py` | `redis_sink.py` | Redis replaces polling |
| `node_logger.py` | WAL events `NODE_RESULT_PRODUCED` | Structured events |
| `materialize.py` | `views/intermediate.py:build_ir()` | IR from WAL |
| `runner.py:create_run_timestamp_dir()` | `run_dir.py:create_run_directory()` | epoch_ms + git SHA |

---

# 21. FILE-BY-FILE CHANGE PLAN

**New files:**

| File | Purpose |
|------|---------|
| `core/logging_v2/__init__.py` | Package |
| `core/logging_v2/enums.py` | All enums (EventType, Emitter, RunStatus, CallStatus, Axis, RedisWriteMode, RedisFailureMode, ViewName, StatName) |
| `core/logging_v2/config.py` | LoggingV2Config + validate_config |
| `core/logging_v2/axes.py` | AxisSpec, AXIS_ORDER, AXIS_SPECS |
| `core/logging_v2/paths.py` | build_artifact_path (single function) |
| `core/logging_v2/run_dir.py` | create_run_directory |
| `core/logging_v2/manifest.py` | RunManifest + transition_status + ALLOWED_TRANSITIONS |
| `core/logging_v2/events.py` | WALEvent + validate_event + validate_axis_consistency |
| `core/logging_v2/event_types.py` | EventTypeSpec + EVENT_TYPE_SPECS |
| `core/logging_v2/wal_writer.py` | WALWriter |
| `core/logging_v2/sinks.py` | Sink protocol |
| `core/logging_v2/call_artifacts.py` | CallArtifact + write_call_json + write_call_txt + render_call_txt |
| `core/logging_v2/redis_sink.py` | RedisSink |
| `core/logging_v2/validation.py` | Pre-run validation checks |
| `core/logging_v2/views/__init__.py` | Package |
| `core/logging_v2/views/registry.py` | VIEW_REGISTRY + ViewSpec |
| `core/logging_v2/views/intermediate.py` | RunIR + build_ir |
| `core/logging_v2/views/rebuild.py` | rebuild_views |
| `core/logging_v2/views/renderers.py` | Pure render functions |
| `core/logging_v2/stats/__init__.py` | Package |
| `core/logging_v2/stats/registry.py` | STAT_REGISTRY + StatSpec |
| `core/logging_v2/stats/builtins.py` | Compute functions |

**Existing files modified (Phase 2):**

| File | Change |
|------|--------|
| `graph/scheduler.py` | Emit engine WAL events via WALWriter |
| `control/run_single_attempt.py` | Use WALWriter + call_artifacts |
| `control/retry_controller.py` | Emit controller WAL events |
| `runner.py` | `logs_v2` backend dispatch |

**Files deprecated (Phase 4):**

| File | Replaced by |
|------|------------|
| `call_logger.py` | `call_artifacts.py` |
| `prompt_store.py` | `call_artifacts.py` |
| `v2_dashboard.py` | `views/` |
| `v2_metrics.py` | `stats/` |
| `live_metrics.py` | `redis_sink.py` |

---

# 22. MIGRATION PHASES

**Phase 1:** Schema + writer + validation. All `core/logging_v2/` files. Unit tests. No integration.

**Phase 2:** Graph-runner integration. Engine and controller emit WAL events. Calls write to axis-structured directories.

**Phase 3:** Materialized views + stats. Views generated from WAL. Stats computed from IR.

**Phase 4:** V2 retirement. Old logging modules deprecated after full graph migration.

---

# 23. TEST PLAN

| Module | Tests |
|--------|-------|
| `test_enums.py` | All enum members exist, no duplicates, JSON-serializable |
| `test_axes.py` | AXIS_ORDER length, AXIS_SPECS completeness, zero-index enforcement |
| `test_paths.py` | build_artifact_path produces exact expected paths, rejects missing required axes, rejects unsafe strings, rejects negative trial/path |
| `test_run_dir.py` | Naming format, uniqueness, collision retry, atomic creation |
| `test_manifest.py` | Schema, immutable fields, status transitions (valid + invalid), crash detection |
| `test_wal_writer.py` | Emission, monotonic seq, fsync, validation rejection, sink isolation |
| `test_events.py` | validate_event all checks, validate_axis_consistency all checks |
| `test_event_types.py` | Registry completeness (every EventType has a spec), emitter match, requires_case/call_id |
| `test_call_artifacts.py` | JSON write + verify, TXT render format, write ordering (JSON before WAL before TXT), hash correctness |
| `test_config.py` | validate_config accepts valid, rejects invalid redis modes, rejects bad separator |
| `test_validation.py` | Node uniqueness, filesystem safety, model normalization, config hash, trial zero-index |
| `test_views.py` | build_ir from WAL, view purity (no side effects), all views render without error |
| `test_stats.py` | All StatName members have registry entries, compute functions produce dicts |
| `test_redis_sink.py` | Emit, flush, failure modes, disabled mode |
| `test_reconstruction.py` | WAL + call artifacts sufficient to rebuild IR, rebuild views match original |
| `test_crash_recovery.py` | Truncated WAL readable, missing .txt recoverable, manifest status detection |
| `test_zero_index.py` | Trial values in events/paths/manifests are always >= 0 |
| `test_model_normalization.py` | Model names in events match config exactly |

---

# 24. NON-NEGOTIABLE INVARIANTS

1. WAL + call artifacts are the ONLY canonical objects.
2. No global mutable logger state. WALWriter is passed explicitly.
3. No run directory reuse. Epoch-ms + atomic mkdir.
4. Trial indexing is zero-based. Everywhere.
5. Path indexing is zero-based. Everywhere.
6. Axis ordering defined once in `axes.py`. All path builders use `build_artifact_path`.
7. Event types are `EventType` enum members. No raw strings in control flow.
8. Emitters are `Emitter` enum members. No raw strings.
9. Statuses are `RunStatus`/`CallStatus` enum members.
10. Call artifacts always have both .json and .txt.
11. .json is written and fsynced BEFORE WAL event is emitted.
12. .txt is written AFTER WAL event.
13. Materialized views are pure functions of RunIR. No side effects in renderers.
14. Redis failure never blocks WAL writes.
15. Manifest status transitions are enforced by `transition_status()`. Invalid transitions raise.
16. Node names validated unique and filesystem-safe before run starts.
17. All semantic identifiers (case IDs, condition names, model names) used directly in directory names. No synthetic labels.
18. Stats are `StatName` enum members. Registry-driven. Adding a stat = one enum + one function + one registry entry.

---

# 25. OPEN QUESTIONS (RESOLVED)

| Question | Decision |
|----------|----------|
| Orchestrator WAL | Separate `orchestrator_wal.jsonl` in experiment root. Per-worker WALs in worker run dirs. |
| Event merging for multi-worker | Per-worker WALs. `rebuild.py` provides merge utility. No implicit merging. |
| Call artifact size | Full prompt + response stored. Accept disk cost. Gzip compression is NOT added in v1. |
