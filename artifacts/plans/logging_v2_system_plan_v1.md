Date: 2026-04-10
Time: 01:00

# LOGGING V2 SYSTEM PLAN v1

---

# 1. EXECUTIVE SUMMARY

This plan defines a complete replacement for the current logging and run-artifact system. The new system treats the WAL and call artifacts as the two canonical objects from which everything else is derived. It introduces a structured run directory layout under `logs_v2/`, a typed WAL event schema, axis-aware artifact directories, a configurable materialized-view system, and optional Redis streaming. The existing V2 logging system (`core/logging_/`) remains untouched until the new system is validated and the graph-runner migration is complete.

---

# 2. CURRENT-SYSTEM RISKS BEING ELIMINATED

| Risk | Description |
|------|-------------|
| Run directory reuse | Current `create_run_timestamp_dir()` uses `HH-MM-SS` granularity. Two runs in the same second collide. No epoch-ms or git SHA. |
| Global mutable logger state | `call_logger.py` uses 6 module-level globals. `RunLogger` owns trace/trajectory state. |
| Dual event schema | Every event has `event_type` (legacy), `event_type_canonical` (authoritative), and `payload` (compat blob). |
| Manual parent ID threading | `last_parent_eid` is manually updated through 200+ lines of retry loop logic. |
| No graph engine WAL | Graph engine lifecycle events go to Python stdlib logging, not WAL. |
| Parallel logging paths | `call_logger.py` and `RunLogger.log_call()` both write `calls/*.json`. `run.jsonl` parallels `events.jsonl`. |
| Hardcoded strings everywhere | Directory prefixes, axis ordering, formatting, node names, status labels are scattered across modules. |
| No experiment stamp | Run directories do not contain experiment name or git SHA. |
| No configurable stats | Dashboard/metrics are hardcoded per-field, not registry-driven. |

---

# 3. CANONICAL CONCEPTS AND TERMINOLOGY

| Term | Definition | Fixed or Configurable |
|------|-----------|----------------------|
| condition | Experimental condition / prompting regime / controller regime. First-class axis. | Config-driven. Names from YAML `conditions` section. |
| model | LLM model identity. First-class axis. Normalized via model registry. | Config-driven. Names from YAML `models` section. |
| case | Semantic case identifier (e.g., `alias_config_c`). First-class axis. | Data-driven. IDs from `cases_v2.json`. |
| trial | Zero-indexed retry/attempt index within one (condition, model, case) tuple. | Fixed: always zero-indexed. |
| path | One concrete execution flow within a trial. `path_0` today. | Fixed prefix: `path_`. Future: multiple paths for branching. |
| node | Graph node identity from the validated node registry. | Registry-driven. From `control/registry.py`. |
| call | A single LLM/API/tool invocation unit. Sequentially numbered per (trial, path, node). | Fixed prefix: `call_`. |
| WAL | Write-ahead log. Append-only JSONL. Canonical truth alongside call artifacts. | Fixed filename: `wal.jsonl`. |
| call artifact | Pair of `.json` (machine-readable) + `.txt` (human-readable) files per LLM call. | Fixed format. |
| materialized view | Derived human-readable or aggregate rendering. NOT canonical truth. | Registry-driven. |
| manifest | Run-root metadata file. Immutable fields + status transitions. | Fixed filename: `manifest.json`. |

---

# 4. FINAL RUN DIRECTORY NAMING SPECIFICATION

**Format:**
```
{YYYY-MM-DD}_{HH-MM-SS}-{epoch_ms}-{git_sha_prefix}_{experiment_name}
```

**Example:**
```
2026-04-09_23-30-12-1712705412483-a1b2c3_ablation_ddc_4omini
```

**Rules:**
- `YYYY-MM-DD` and `HH-MM-SS` from UTC wall clock
- `epoch_ms` = `int(time.time() * 1000)` — millisecond precision ensures uniqueness
- `git_sha_prefix` = first 6 characters of `git rev-parse HEAD` (or `nogit` if not a git repo)
- `experiment_name` = `config.experiment.name` with non-filesystem characters replaced by `_`
- One underscore before experiment_name
- No double underscores anywhere
- No timezone suffix
- No `run` prefix
- Directory created with `os.mkdir()` (not `exist_ok=True`) — collision raises immediately
- On collision (epoch_ms same within 1ms): sleep 1ms and retry once, then fail

**Location:** `logs_v2/{run_dir_name}/`

**Owner function:** `core/logging_v2/run_dir.py:create_run_directory(config) -> Path`

---

# 5. FINAL INSIDE-RUN DIRECTORY STRUCTURE

```
logs_v2/{run_dir_name}/
  manifest.json
  wal.jsonl
  artifacts/
    calls/
      {condition}/
        {model}/
          {case}/
            trial_{i}/
              path_{j}/
                {node}/
                  call_001.json
                  call_001.txt
                  call_002.json
                  call_002.txt
    execution/
      {condition}/
        {model}/
          {case}/
            trial_{i}/
              path_{j}/
                stdout.txt
                stderr.txt
                result.json
    diffs/
      {condition}/
        {model}/
          {case}/
            trial_{i}/
              path_{j}.diff
  materialized_views/
    summary.md
    timeline.md
    failures.md
    llm_calls.md
    trial_table.md
    cases/
      {case_id}.md
    index.json
```

**Axis ordering (fixed, centralized):**
1. condition
2. model
3. case
4. trial_{i}
5. path_{j}
6. node (for calls only)
7. call_{k} (for calls only)

This ordering is defined ONCE in `core/logging_v2/axes.py` and used by all path builders.

---

# 6. EXACT MANIFEST SCHEMA

**File:** `manifest.json` at run root.

```python
@dataclass
class RunManifest:
    # Identity (immutable after creation)
    run_id: str                    # UUID hex
    run_dir_name: str              # directory name
    experiment_name: str           # from config.experiment.name
    experiment_description: str    # from config.experiment.description
    experiment_tags: list[str]     # from config.experiment.tags
    seed: int                      # from config.experiment.seed
    config_path: str               # path to YAML config used
    config_hash: str               # SHA256 of config file content
    
    # Git (immutable)
    git_commit_sha: str            # full 40-char SHA
    git_short_sha: str             # 6-char prefix used in dir name
    git_branch: str                # branch name
    git_dirty: bool                # True if uncommitted changes
    
    # Timestamps
    start_timestamp: str           # ISO 8601 UTC
    end_timestamp: str | None      # ISO 8601 UTC, None until run ends
    
    # Status (mutable: pending → running → completed | failed | crashed)
    status: str                    # "pending" | "running" | "completed" | "failed" | "crashed"
    
    # Models (immutable)
    models: list[dict]             # [{name, temperature, max_tokens, top_p, role}]
    
    # Parallelism (immutable)
    num_workers: int
    worker_timeout_seconds: int
    
    # Logging config (immutable)
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

**Status transitions:**
- `pending` → `running` (on first event emission)
- `running` → `completed` (on successful run end)
- `running` → `failed` (on handled failure)
- `running` → `crashed` (on unhandled exception / process death detected by manifest timestamp gap)
- `pending` → `crashed` (if process dies before first event)

**Immutable fields:** Everything except `end_timestamp` and `status`.

**Write protocol:**
1. `manifest.json` written atomically at run start with `status: "pending"`
2. Updated to `status: "running"` on first event
3. Updated to `status: "completed"` or `status: "failed"` at run end
4. If process crashes, manifest stays at `"running"` — detected by missing `end_timestamp`

**Owner:** `core/logging_v2/manifest.py:write_manifest()`, `update_manifest_status()`

---

# 7. EXACT LOGGING/ARTIFACT CONFIGURATION SCHEMA

**File:** `core/logging_v2/config.py`

```python
@dataclass(frozen=True)
class LoggingV2Config:
    schema_version: str = "2.0"
    wal_filename: str = "wal.jsonl"
    artifacts_dirname: str = "artifacts"
    calls_dirname: str = "calls"
    execution_dirname: str = "execution"
    diffs_dirname: str = "diffs"
    materialized_views_dirname: str = "materialized_views"
    
    # Axis config
    trial_prefix: str = "trial_"
    path_prefix: str = "path_"
    call_prefix: str = "call_"
    
    # Call text formatting
    call_txt_request_header: str = "=" * 80 + "\n REQUEST \n" + "=" * 80
    call_txt_response_header: str = "=" * 80 + "\n RESPONSE \n" + "=" * 80
    call_txt_metadata_header: str = "=" * 80 + "\n METADATA \n" + "=" * 80
    
    # Redis
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "t3_events"
    redis_write_mode: str = "async_buffered"  # "sync" | "async_buffered"
    redis_failure_mode: str = "log_and_continue"  # "log_and_continue" | "raise"
```

**Validation:** At startup, `validate_logging_config(config)` checks:
- `schema_version` is "2.0"
- `redis_write_mode` in `{"sync", "async_buffered"}`
- `redis_failure_mode` in `{"log_and_continue", "raise"}`
- all prefix strings are non-empty and contain no path separators

**Owner:** `core/logging_v2/config.py`

---

# 8. EXACT WAL/EVENT SCHEMA STRATEGY

**File:** `core/logging_v2/events.py`

Every WAL event is a single JSON line conforming to this envelope:

```python
@dataclass(frozen=True)
class WALEvent:
    event_id: str               # run-unique monotonic "{seq:08d}"
    event_type: str             # from EVENT_TYPE_REGISTRY
    schema_version: str         # "2.0"
    timestamp: str              # ISO 8601 UTC
    seq: int                    # monotonic append order
    
    # Lineage
    run_id: str
    case_id: str | None
    condition: str | None
    model: str | None
    trial: int | None           # zero-indexed
    path: int | None            # zero-indexed
    node: str | None
    
    # Causality
    parent_event_id: str | None
    trace_id: str | None
    
    # Ownership
    emitter: str                # "engine" | "controller" | "runner" | "node"
    
    # Payload
    payload: dict               # event-type-specific structured data
```

**Event type registry** (defined in `core/logging_v2/event_types.py`):

```python
EVENT_TYPE_REGISTRY: dict[str, dict] = {
    # Run lifecycle
    "run.started":                {"emitter": "runner", "requires_case": False},
    "run.completed":              {"emitter": "runner", "requires_case": False},
    "run.failed":                 {"emitter": "runner", "requires_case": False},
    
    # Case lifecycle
    "case.started":               {"emitter": "runner", "requires_case": True},
    "case.completed":             {"emitter": "runner", "requires_case": True},
    "case.failed":                {"emitter": "runner", "requires_case": True},
    
    # Engine lifecycle
    "engine.graph.started":       {"emitter": "engine", "requires_case": True},
    "engine.graph.completed":     {"emitter": "engine", "requires_case": True},
    "engine.graph.failed":        {"emitter": "engine", "requires_case": True},
    "engine.node.started":        {"emitter": "engine", "requires_case": True},
    "engine.node.completed":      {"emitter": "engine", "requires_case": True},
    "engine.node.failed":         {"emitter": "engine", "requires_case": True},
    "engine.node.skipped":        {"emitter": "engine", "requires_case": True},
    "engine.merge.completed":     {"emitter": "engine", "requires_case": True},
    
    # Controller lifecycle
    "controller.attempt.started":  {"emitter": "controller", "requires_case": True},
    "controller.attempt.completed":{"emitter": "controller", "requires_case": True},
    "controller.retry.decided":    {"emitter": "controller", "requires_case": True},
    "controller.critique.generated":{"emitter": "controller", "requires_case": True},
    "controller.result.selected":  {"emitter": "controller", "requires_case": True},
    
    # LLM calls
    "llm.call.started":           {"emitter": "node", "requires_case": True},
    "llm.call.completed":         {"emitter": "node", "requires_case": True},
    "llm.call.failed":            {"emitter": "node", "requires_case": True},
    
    # Node results
    "node.result.produced":       {"emitter": "node", "requires_case": True},
}
```

**Validation at emission:** `core/logging_v2/events.py:validate_event(event)` checks:
- `event_type` in `EVENT_TYPE_REGISTRY`
- `emitter` matches registry declaration
- `case_id` is non-None when `requires_case` is True
- `seq` is strictly monotonic
- `schema_version` is "2.0"
- `trial` is None or >= 0 (zero-indexed enforcement)

---

# 9. EXACT CALL ARTIFACT SCHEMAS

**Machine-readable: `call_{k}.json`**

```python
@dataclass
class CallArtifact:
    call_id: str                # "{seq:08d}" matching WAL event
    event_id: str               # WAL event_id that references this call
    timestamp: str              # ISO 8601 UTC
    model: str
    node: str
    phase: str                  # "generation" | "classification" | "oracle" | "critique"
    
    # Context
    run_id: str
    case_id: str
    condition: str
    trial: int
    path: int
    
    # Request
    prompt: str                 # FULL prompt text
    prompt_hash: str            # SHA256 of prompt
    prompt_length: int
    temperature: float
    top_p: float
    max_tokens: int | None
    
    # Response
    response: str               # FULL response text
    response_hash: str          # SHA256 of response
    response_length: int
    
    # Timing
    latency_ms: int
    
    # Status
    status: str                 # "success" | "error"
    error: str | None
```

**Owner:** `core/logging_v2/call_artifacts.py:write_call_artifact(run_root, call)`

---

# 10. HUMAN-READABLE CALL TEXT FORMAT SPEC

**File:** `call_{k}.txt`

Format is centrally defined in `core/logging_v2/config.py` via `LoggingV2Config.call_txt_*_header` fields.

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
{full prompt text, untruncated}

================================================================================
 RESPONSE
================================================================================
{full response text, untruncated}
```

**Rules:**
- Section headers are 80-char `=` bars with centered label
- Full prompt and full response, never truncated
- Metadata section first (human scans top-down)
- Format string templates live in `LoggingV2Config`, not scattered in code
- Rendering function: `core/logging_v2/call_artifacts.py:render_call_txt(call, config)`

---

# 11. MATERIALIZED VIEWS ARCHITECTURE

**Directory:** `materialized_views/` at run root.

**Design:** Registry-driven. Each view is a registered renderer.

**File:** `core/logging_v2/views/registry.py`

```python
VIEW_REGISTRY: dict[str, ViewSpec] = {
    "summary":     ViewSpec(filename="summary.md",     renderer=render_summary),
    "timeline":    ViewSpec(filename="timeline.md",     renderer=render_timeline),
    "failures":    ViewSpec(filename="failures.md",     renderer=render_failures),
    "llm_calls":   ViewSpec(filename="llm_calls.md",    renderer=render_llm_calls),
    "trial_table": ViewSpec(filename="trial_table.md",  renderer=render_trial_table),
    "index":       ViewSpec(filename="index.json",      renderer=render_index),
}
```

Each renderer has signature: `render_X(intermediate_repr: RunIR, config: LoggingV2Config) -> str`

**Intermediate representation:** `core/logging_v2/views/intermediate.py`

```python
@dataclass
class RunIR:
    """Stable intermediate representation built from WAL + call artifacts.
    All views derive from this. Never from runtime state."""
    manifest: RunManifest
    events: list[WALEvent]
    calls: list[CallArtifact]
    # Derived indexes (built once, reused by all views)
    events_by_case: dict[str, list[WALEvent]]
    events_by_type: dict[str, list[WALEvent]]
    calls_by_case: dict[str, list[CallArtifact]]
    calls_by_node: dict[str, list[CallArtifact]]
```

**Rebuild:** `core/logging_v2/views/rebuild.py:rebuild_views(run_root: Path, config: LoggingV2Config)`
- Reads WAL + call artifacts
- Builds RunIR
- Iterates VIEW_REGISTRY
- Writes each view to `materialized_views/`

**Case deep dives:** For each case_id in the run, `cases/{case_id}.md` is generated by `render_case_detail(case_id, ir, config)`.

---

# 12. STATISTICS / AGGREGATION EXTENSION MECHANISM

**File:** `core/logging_v2/stats/registry.py`

```python
STAT_REGISTRY: dict[str, StatSpec] = {
    "pass_rate":           StatSpec(compute=compute_pass_rate,      axes=["condition", "model"]),
    "leg_rate":            StatSpec(compute=compute_leg_rate,        axes=["condition", "model"]),
    "attempt_count":       StatSpec(compute=compute_attempt_count,   axes=["condition", "model", "case"]),
    "parse_success_rate":  StatSpec(compute=compute_parse_rate,      axes=["condition", "model"]),
    "mean_latency_ms":     StatSpec(compute=compute_mean_latency,    axes=["condition", "model", "node"]),
}
```

Each stat function signature: `compute_X(ir: RunIR, axes: list[str]) -> dict`

**Adding a new stat:** Add one entry to `STAT_REGISTRY`. The materialized summary view auto-includes all registered stats. No other code changes needed.

**Owner:** `core/logging_v2/stats/`

---

# 13. REDIS STREAMING ARCHITECTURE

**File:** `core/logging_v2/redis_sink.py`

**Design:**
- Redis receives the SAME `WALEvent` objects as the WAL file, serialized to JSON
- Redis stream name from `LoggingV2Config.redis_stream_name`
- Write mode: `async_buffered` (default) — events buffered and flushed in batches. `sync` — write per event.
- On failure: `log_and_continue` (default) — log warning, continue. `raise` — propagate exception.

**Protocol:**
```python
class RedisSink:
    def __init__(self, config: LoggingV2Config) -> None: ...
    def emit(self, event: WALEvent) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

**Decoupling:** Redis sink is instantiated only if `config.redis_enabled`. WALWriter has an optional `sinks: list[Sink]` parameter. RedisSink is one possible sink. WAL file write is always the primary; sinks are secondary.

**Consumers:** Redis consumers can subscribe to the stream and build live dashboards. They rebuild state from the event stream. If a consumer misses events, it can rebuild from WAL.

---

# 14. VALIDATION RULES AND STARTUP CHECKS

**File:** `core/logging_v2/validation.py`

Executed BEFORE any run starts:

| Check | Description | Failure mode |
|-------|------------|-------------|
| Node name uniqueness | All node IDs in registry are unique | `RuntimeError` |
| Node names filesystem-safe | No `/`, `\`, `:`, `..` in node names | `RuntimeError` |
| Condition names filesystem-safe | Same rules as node names | `RuntimeError` |
| Model names normalized | Model names match config exactly, no aliases | `RuntimeError` |
| Case IDs filesystem-safe | No path separators in case IDs | `RuntimeError` |
| Config hash matches | Config file content hash matches manifest | `RuntimeError` |
| Git SHA resolvable | `git rev-parse HEAD` succeeds or returns `"nogit"` | Warning only |
| Run directory does not exist | Target path must not already exist | `RuntimeError` |
| WAL file does not exist | No pre-existing `wal.jsonl` | `RuntimeError` |
| Redis reachable (if enabled) | Ping Redis server | Warning (log_and_continue) or `RuntimeError` (raise mode) |

---

# 15. WRITE ORDERING / ATOMICITY / CRASH SEMANTICS

**Run creation protocol:**
1. Compute run directory name
2. `os.mkdir(run_dir)` — atomic, fails on collision
3. Write `manifest.json` atomically (temp + fsync + rename) with `status: "pending"`
4. Open `wal.jsonl` for append
5. Update manifest to `status: "running"`
6. Begin execution

**Event write protocol:**
1. Serialize WALEvent to JSON line
2. Append to `wal.jsonl`
3. `flush()` + `fsync()`
4. If redis enabled: emit to redis sink (non-blocking if async_buffered)

**Call artifact write protocol:**
1. Create directory path (all axis directories)
2. Write `call_{k}.json` atomically (temp + fsync + rename)
3. Write `call_{k}.txt` atomically (temp + fsync + rename)
4. Emit `llm.call.completed` WAL event referencing artifact path

**Crash semantics:**
- Incomplete runs have `manifest.json` with `status: "running"` and no `end_timestamp`
- WAL may be truncated mid-line — readers skip malformed trailing lines
- Call artifacts are atomic — either fully written or absent
- Materialized views may be stale — rebuild from WAL + artifacts
- No run directory is ever reused or overwritten

---

# 16. MAPPING FROM EXISTING SYSTEM TO NEW SYSTEM

| Old Component | New Component | Action |
|---|---|---|
| `core/logging_/logging_core.py:RunLogger` | `core/logging_v2/wal_writer.py:WALWriter` | New stateless writer. No trace/trajectory state. |
| `core/logging_/logging_core.py:OrchestratorLogger` | `core/logging_v2/wal_writer.py:WALWriter` (same class, different run) | Unified writer. |
| `core/logging_/call_logger.py` | `core/logging_v2/call_artifacts.py` | New module. call_logger.py global state eliminated. |
| `core/logging_/prompt_store.py` | Absorbed into `call_artifacts.py` | Prompt text now part of call .txt file. |
| `core/logging_/v2_metrics.py` | `core/logging_v2/stats/` | Registry-driven stats from RunIR. |
| `core/logging_/v2_dashboard.py` | `core/logging_v2/views/` | Registry-driven materialized views. |
| `core/logging_/live_metrics.py` | `core/logging_v2/redis_sink.py` + consumer | Redis replaces polling. |
| `core/logging_/node_logger.py` | WAL events with `emitter: "node"` | Validation warnings become node.result.produced events. |
| `core/evaluation/materialize.py` | `core/logging_v2/views/intermediate.py:build_ir()` | IR built from WAL, not from ad-hoc event parsing. |
| `runner.py:create_run_timestamp_dir()` | `core/logging_v2/run_dir.py:create_run_directory()` | New naming with epoch_ms + git SHA. |

---

# 17. EXACT FILE-BY-FILE CHANGE PLAN

**New files to create:**

| File | Purpose |
|------|---------|
| `core/logging_v2/__init__.py` | Package init |
| `core/logging_v2/config.py` | LoggingV2Config dataclass + validation |
| `core/logging_v2/run_dir.py` | Run directory creation + naming |
| `core/logging_v2/manifest.py` | RunManifest schema + write/update |
| `core/logging_v2/events.py` | WALEvent dataclass + EVENT_TYPE_REGISTRY + validation |
| `core/logging_v2/event_types.py` | Event type registry (closed vocabulary) |
| `core/logging_v2/wal_writer.py` | WALWriter class (stateless, append-only) |
| `core/logging_v2/call_artifacts.py` | CallArtifact schema + write .json/.txt + render_call_txt |
| `core/logging_v2/axes.py` | Axis ordering, prefix config, path builders |
| `core/logging_v2/validation.py` | Pre-run validation checks |
| `core/logging_v2/redis_sink.py` | Redis streaming sink |
| `core/logging_v2/views/__init__.py` | Views package |
| `core/logging_v2/views/registry.py` | VIEW_REGISTRY + ViewSpec |
| `core/logging_v2/views/intermediate.py` | RunIR dataclass + build_ir() |
| `core/logging_v2/views/rebuild.py` | rebuild_views() |
| `core/logging_v2/views/renderers.py` | Individual view render functions |
| `core/logging_v2/stats/__init__.py` | Stats package |
| `core/logging_v2/stats/registry.py` | STAT_REGISTRY + StatSpec |
| `core/logging_v2/stats/builtins.py` | Built-in stat compute functions |

**Existing files to modify (Phase 2+):**

| File | Change |
|------|--------|
| `side_projects/graph_runner/graph/scheduler.py` | Emit engine WAL events via WALWriter instead of stdlib logging |
| `side_projects/graph_runner/control/run_single_attempt.py` | Use WALWriter for case lifecycle |
| `side_projects/graph_runner/control/retry_controller.py` | Emit controller WAL events |
| `core/pipeline/orchestration/runner.py` | Add `logs_v2` backend dispatch; create run dir via new system |

**Files to deprecate (Phase 3, after validation):**

| File | Reason |
|------|--------|
| `core/logging_/call_logger.py` | Replaced by `call_artifacts.py` |
| `core/logging_/prompt_store.py` | Absorbed into `call_artifacts.py` |
| `core/logging_/v2_dashboard.py` | Replaced by `views/` |
| `core/logging_/v2_metrics.py` | Replaced by `stats/` |
| `core/logging_/live_metrics.py` | Replaced by `redis_sink.py` |

**Files NOT modified:**

| File | Reason |
|------|--------|
| `core/logging_/logging_core.py` | V2 pipeline continues using it until retirement |
| `core/pipeline/orchestration/execution_v2.py` | V2 pipeline untouched |
| `core/pipeline/orchestration/retry_v2.py` | V2 pipeline untouched |

---

# 18. MIGRATION PHASES

**Phase 1: Schema + Writer + Validation (no integration)**
- Create all `core/logging_v2/` files
- WALWriter, WALEvent, CallArtifact, RunManifest, axes, config, validation
- Unit tests for each module
- No connection to graph runner or V2 pipeline

**Phase 2: Graph-Runner Integration**
- Graph engine scheduler emits engine WAL events via WALWriter
- Controller emits controller WAL events
- run_single_attempt creates run dir via new system, writes to `logs_v2/`
- Graph backend dispatch creates WALWriter and passes via ExecutionContext
- Call artifacts written to axis-structured directories
- Materialized views generated after run

**Phase 3: Dual-Mode Validation**
- Shadow mode runs both V2 logging and V2 logging paths
- Compare outputs: WAL event count, call artifact count, final results
- Validate materialized views match v2_dashboard output

**Phase 4: V2 Retirement (future, after full graph migration)**
- V2 pipeline switches to logging_v2
- Old logging modules deprecated
- Analysis scripts updated to read new WAL schema

---

# 19. TEST PLAN

| Test Module | Tests |
|---|---|
| `test_run_dir.py` | Directory naming format, uniqueness, collision handling, atomic creation |
| `test_manifest.py` | Schema validation, status transitions, immutable fields, crash detection |
| `test_wal_writer.py` | Event emission, monotonic seq, fsync, schema validation, malformed rejection |
| `test_event_types.py` | Registry completeness, emitter validation, requires_case enforcement |
| `test_call_artifacts.py` | JSON + TXT write, format correctness, hash verification, axis path construction |
| `test_axes.py` | Path building, ordering, prefix application, filesystem safety |
| `test_validation.py` | All startup checks: node uniqueness, filesystem safety, config hash, git SHA |
| `test_views.py` | IR construction from WAL, view rendering, registry completeness |
| `test_stats.py` | Stat computation from IR, registry extension |
| `test_redis_sink.py` | Emit, flush, failure modes, enable/disable |
| `test_integration_e2e.py` | Full run: create dir → emit events → write calls → rebuild views → validate |

---

# 20. NON-NEGOTIABLE INVARIANTS

1. WAL + call artifacts are the ONLY canonical objects. Everything else is derived.
2. No global mutable logger state. WALWriter is passed explicitly.
3. No run directory reuse. Epoch-ms + atomic mkdir guarantees uniqueness.
4. Trial indexing is always zero-based. Everywhere. No exceptions.
5. Axis ordering is defined once in `axes.py`. All path builders use it.
6. Event types come from `EVENT_TYPE_REGISTRY`. No ad-hoc strings.
7. Node names come from `control/registry.py`. No invented names in logging code.
8. Call artifacts always have BOTH .json and .txt. Neither is optional.
9. Materialized views are always rebuildable from WAL + call artifacts.
10. Redis failure never blocks WAL writes (in `log_and_continue` mode).
11. Manifest status transitions are monotonic: pending → running → terminal.
12. All directory names use real semantic identifiers (case IDs, condition names, model names). No synthetic labels.

---

# 21. EXPLICIT OPEN QUESTIONS

1. **Orchestrator events.** The orchestrator (multi-worker coordinator) currently has its own OrchestratorLogger. Should it write to the same `logs_v2/` WAL, or maintain a separate experiment-level WAL? Proposal: separate `logs_v2/{experiment_dir}/orchestrator_wal.jsonl` for worker lifecycle, with per-worker WALs inside worker run dirs.

2. **Event merging for multi-worker.** The current system merges worker events into `merged_events.jsonl`. The new system could either: (a) merge WALs post-run into a combined view, or (b) keep per-worker WALs and have readers aggregate. Proposal: keep per-worker WALs, provide a merge utility in `views/rebuild.py`.

3. **Call artifact size limits.** Some prompts/responses are 100KB+. The new system stores full text in both .json and .txt. Disk usage could be significant for large runs. Proposal: accept this cost. Full preservation is a stated requirement. If needed later, add optional gzip compression for .json files.
