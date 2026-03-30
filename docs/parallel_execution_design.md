# Parallel Execution Design

## 0. System Understanding

Before proposing changes, the relevant architectural facts:

**Execution unit:** `(case_id, condition)` processed by `_run_one()`. Each unit is
independent: it reads from `cases_v2.json` (immutable) and the prompt templates
(immutable), calls the OpenAI API, runs local execution tests, calls the classifier
API, and emits log events. No unit reads another unit's output.

**Logger:** `RunLogger` (logging_core.py) is created once per run in `run_ablation_mode()`.
It holds an open file handle to `events.jsonl`, maintains a monotonic `_event_counter`,
and writes all events through `_write_event()`. The RunLogger is passed explicitly
through the entire call stack. It is documented as "NEVER pickled. NEVER passed
through ProcessPoolExecutor."

**File writes:**
- `events.jsonl`: via `RunLogger._write_event()` — Python `file.write()` + `flush()`,
  with conditional `fsync()` for critical events. Single file handle, monotonic event_id.
- `run.jsonl`: via `RunLogger.log_run()` — `os.open/os.write/os.fsync/os.close` per event.
- `calls/{id}.json`: via `write_json_atomic()` — temp file + fsync + `os.replace()`.
- `calls_flat/{id}_{phase}.txt`: via `write_text_atomic()` — same atomic pattern.

**Global state:** `experiment_config` is a read-only singleton set once at startup.
`call_logger.py` has module-level globals (`_call_counter`, `_call_context`, etc.)
that are set per-call. `redis_metrics.py` has a lazy-init connection.

**Resume:** `load_completed_pairs()` reads `events.jsonl` and returns a set of
`(case_id, condition)` tuples. `run_all()` skips pairs in this set.

---

## 1. Execution Model

### Unit of parallelization

**One subprocess per case-file chunk.** Not per `(case, condition)` pair, not per
condition, not per API call. Each subprocess gets a disjoint subset of cases and
runs ALL conditions for those cases sequentially within that subprocess.

### Why this unit

- **Independence:** Each case's execution is fully independent — it reads immutable
  inputs and writes to its own trace. No case reads another case's output during
  execution.
- **Logger safety:** Each subprocess creates its OWN `RunLogger` writing to its OWN
  output directory. No shared file handles. No shared monotonic counters. No
  interleaved writes.
- **call_logger safety:** The module-level globals in `call_logger.py` (`_call_counter`,
  `_call_context`) are per-process. Each subprocess gets its own copy after fork.
  No contention.
- **experiment_config safety:** Read-only singleton. Safe to share across processes
  (loaded before fork, never mutated).
- **OpenAI client safety:** Each subprocess creates its own client connection. No
  shared socket state.

### Why NOT per-(case, condition) pair

Spawning 174 processes (58 cases x 3 conditions) is excessive. The overhead of
process creation, config loading, and OpenAI client initialization per pair would
dominate. Case-level chunking gives N processes each running 3 conditions serially
per case, which is simple and efficient.

### Why NOT async within a process

Async would require rewriting `call_model()`, `exec_evaluate()`, and all downstream
functions. It also introduces cooperative scheduling complexity and error handling
changes throughout the stack. Process-level parallelism requires zero changes to the
execution pipeline — each process runs the existing serial code unmodified.

### Job creation

The orchestrator (main process) splits the case list into N chunks:

```
cases = load_cases(...)  # 58 cases
chunks = split_into_n(cases, N)  # e.g., 4 chunks of ~15 cases each
```

Each chunk is written to a temporary case file: `cases_chunk_{i}.json`.
Each chunk gets its own YAML config file pointing to its case file and a unique
sub-run directory.

### Job scheduling

All N processes are launched simultaneously via `subprocess.Popen`. The orchestrator
waits for all to complete. No job queue, no dynamic scheduling, no work stealing.
Fixed assignment at launch time.

---

## 2. Process Model

### Number of workers

**N = 4** by default (configurable via `--workers N` in the config YAML). Rationale:

- OpenAI rate limits: tier-dependent, but typically 500-3500 RPM for these models.
  Each worker makes ~2 API calls per (case, condition) pair, so 4 workers = ~8
  concurrent calls. At 20s per call, that's ~24 calls/min — well under rate limits.
- CPU: local execution tests are lightweight. 4 processes on a laptop is comfortable.
- Memory: each process loads cases + config + model client. ~200MB per process.
  4 processes = ~800MB total.

### How workers are spawned

Each worker is a separate `runner.py` invocation via `subprocess.Popen`:

```
.venv/bin/python runner.py --config /tmp/chunk_{i}.yaml
```

This is the existing runner.py entry point, completely unmodified. Each invocation:
1. Loads its chunk config (pointing to `cases_chunk_{i}.json`)
2. Creates its own output directory (`{run_dir}/chunk_{i}/`)
3. Creates its own `RunLogger`
4. Runs `run_all()` serially on its case subset
5. Finalizes and exits

### Worker lifecycle

```
orchestrator:
    1. Load config, load cases, validate
    2. Split cases into N chunks
    3. Write N chunk configs + case files to temp dir
    4. Launch N subprocesses
    5. Wait for all to complete (poll loop with timeout)
    6. Check exit codes
    7. Merge results
    8. Clean up temp files
```

### Worker crash handling

If a worker process exits with non-zero status:

1. The orchestrator logs the failure: which chunk, which exit code, stderr.
2. The orchestrator does NOT retry the worker. (Rationale: the failure may be
   deterministic — retrying wastes API calls. The user can resume manually.)
3. The partial results from the crashed worker's output directory are preserved.
   Events written before the crash are valid (WAL property — every event is
   fsynced/flushed before the next one starts).
4. Other workers continue unaffected (fully isolated processes).
5. The merge step marks the failed chunk's cases as incomplete.
6. The user can resume the failed chunk by running `runner.py --config chunk_N.yaml --resume`.

### Resource contention

- **Files:** Each worker writes to its own directory. Zero contention.
- **OpenAI API:** Shared rate limit. At 4 workers x 2 calls/pair x ~3 pairs/min
  = ~24 RPM. Well under limits. If rate-limited, the SDK's built-in retry handles
  it per-worker.
- **Redis (optional):** Each worker creates its own connection. Redis handles
  concurrent XADD safely.
- **CPU:** exec_evaluate runs sandboxed Python. 4 concurrent sandboxes are fine.

---

## 3. Logging Architecture

### Decision: OPTION B — Per-worker WAL + deterministic merge

Each worker writes to its OWN `events.jsonl`, `run.jsonl`, and `calls/` directory
inside its own output subdirectory. The orchestrator merges them after all workers
complete.

### Why not Option A (shared WAL)

The `RunLogger` holds a persistent file handle and a monotonic event_id counter.
Sharing it across processes would require:
- File locking on every write (performance cost)
- Coordinating the monotonic counter (complexity)
- Handling partial writes from crashed processes (reliability risk)

Per-worker WAL avoids all of this. Each worker's `events.jsonl` is internally
consistent, monotonically ordered, and crash-safe.

### Write mechanism per worker

**Unchanged.** Each worker uses the existing `RunLogger` exactly as today:
- `events.jsonl`: `file.write() + flush()`, conditional `fsync()`
- `run.jsonl`: `os.open/os.write/os.fsync/os.close` per event
- `calls/`: `write_json_atomic()` (temp + fsync + rename)

No new write mechanisms. No locking. No coordination between workers.

### Event ordering

Within each worker: strict monotonic ordering (guaranteed by `_event_counter`).

Across workers: no ordering guarantee. Events from chunk_0 and chunk_1 may overlap
in wall-clock time. The merged `events.jsonl` reconstructs global order by
timestamp (ISO 8601 with microseconds).

### Merge procedure

After all workers complete, the orchestrator:

1. Reads each worker's `events.jsonl` into memory.
2. Re-assigns `event_id` values: monotonic across the merged file, ordered by
   timestamp. Ties broken by (chunk_index, original_event_id).
3. Writes the merged `events.jsonl` to the parent run directory.
4. Concatenates `run.jsonl` files (order does not matter for JSONL — each line
   is self-contained with case_id and condition).
5. Copies `calls/` directories: renames files to avoid collision
   (prefix with chunk index or use globally unique call_ids).
6. Writes `metadata.json` with merge provenance: which chunks, timestamps,
   event counts, any failures.

### Preventing partial writes / corruption

- Each worker's WAL is independent. A crash in worker 2 does not affect worker 1's
  file.
- Every event is flushed before the next API call starts. If the process crashes
  mid-API-call, the last successfully-completed event is in the file.
- The merge step validates each worker's `events.jsonl` (parseable JSONL, monotonic
  event_ids, expected event_type sequences).

### Ensuring EVERY job produces EXACTLY ONE event

- `run_all()` calls `_run_one()` for each (case, condition) pair.
- `_run_one()` calls `logger.start_case()` at the top and either:
  - Returns normally (the execution path logs `case.end` via `logger.end_case()`)
  - Throws an exception (caught, logged via `logger.fail_case()`)
- Both paths emit exactly one terminal event (`case.end` or `case.failed`).
- The merge step validates: for each expected (case_id, condition), exactly one
  terminal event exists. Missing or duplicate events are flagged as errors.

### run_id handling

All workers share the same `run_id` (from the config). Each worker's events include
the `run_id` field. The merged output is a single logical run with one `run_id`.

Worker-specific identity is tracked via a `chunk_id` field added to the config:
e.g., `chunk_id: "chunk_0"`. This is included in `run.start` events for traceability.

---

## 4. Failure + Recovery Model

### Worker crashes mid-job

- The current job's `case.start` event is in the WAL but no `case.end`/`case.failed`.
- The merge step detects this: a `case.start` without a matching terminal event.
- It emits a synthetic `case.failed` event with `error: "worker_crash"`.
- The case is marked incomplete in the merged results.

### API call fails

- Handled by the existing `call_model()` retry/timeout logic (unchanged).
- If all retries fail, the exception propagates to `_run_one()`, which catches it
  and calls `logger.fail_case()`. The case is marked failed with a structured error.

### Parsing fails

- Handled by the existing pipeline. `parse_v2_execution()` returns
  `parse_status="failed"`. The pipeline continues: classifier is skipped, the case
  gets `v2_category="parser_failure_v2"`. A valid event is emitted.

### Evaluation fails

- `exec_evaluate()` runs in a subprocess with a timeout. If it crashes or times out,
  it returns a failure dict. The pipeline continues with `pass=False`.

### Silent data loss prevention

- Every code path through `_run_one()` either returns a result (which `run_all()`
  logs) or raises an exception (which `_run_one()` catches and logs via
  `logger.fail_case()`).
- There is no path where a job is attempted but no event is emitted.
- The merge validation step counts expected vs actual events and flags any mismatch.

---

## 5. Result Consolidation

### Directory structure

```
logs/v2_ablation_nano/
  2026-03-30_12-00-00_v2_ablation_nano_004/     <- parent run dir
    chunk_0/                                     <- worker 0 output
      events.jsonl
      run.jsonl
      calls/
      calls_flat/
      metadata.json
    chunk_1/
      ...
    chunk_2/
      ...
    chunk_3/
      ...
    events.jsonl          <- MERGED (created by orchestrator)
    run.jsonl             <- MERGED
    calls/                <- MERGED (renamed to avoid collision)
    calls_index.json      <- MERGED
    metadata.json         <- orchestrator metadata + merge provenance
    metrics.json          <- derived from merged events.jsonl
```

### Merge procedure (detailed)

1. **Validate each chunk:** Parse every line of each `events.jsonl`. Reject any chunk
   with unparseable lines. Log which chunks are valid.

2. **Merge events.jsonl:**
   - Load all events from all chunks into one list.
   - Sort by `(timestamp, chunk_index, event_id)`.
   - Re-assign `event_id` as 1, 2, 3, ... (global monotonic).
   - Write to parent `events.jsonl`.

3. **Merge run.jsonl:**
   - Concatenate all chunk `run.jsonl` files. No re-ordering needed (each line is
     self-contained).
   - Write to parent `run.jsonl`.

4. **Merge calls/:**
   - Each chunk has `calls/000001.json`, `calls/000002.json`, etc.
   - Rename using global call_id offset: chunk_0 keeps 1-N, chunk_1 starts at N+1, etc.
   - Copy renamed files to parent `calls/`.

5. **Derive metrics.json:**
   - Read merged `events.jsonl`.
   - Count `case.end` events with `pass=True`.
   - Write `metrics.json`.

6. **Validate completeness:**
   - For every expected `(case_id, condition)` pair, verify exactly one terminal
     event exists in the merged `events.jsonl`.
   - Log any missing or duplicate pairs.

### Dashboard/metrics consumption

Existing analysis scripts read `events.jsonl` and `run.jsonl`. After merge, the
parent directory has these files in the standard format. No changes to analysis
scripts.

---

## 6. Reproducibility + Determinism

### Does parallel execution change results?

**No.** Each `(case, condition)` pair runs the same code with the same inputs. The
only source of non-determinism is the OpenAI API (which is non-deterministic even
at temperature=0.0, as observed: 50 case/condition pairs changed between two serial
nano runs). Parallelism adds no new non-determinism.

### Same inputs produce same outputs

Each worker runs `runner.py` with a deterministic config and case list. The pipeline
is serial within each worker. The merge is deterministic (sort by timestamp, ties
broken by chunk_index).

### Debugging a failed run

- Each chunk directory is a complete, self-contained run. It can be analyzed
  independently.
- The orchestrator logs which chunk failed and preserves its stderr.
- The merged `events.jsonl` includes `chunk_id` in event payloads for tracing.
- `--resume` works at the chunk level: re-run only the failed chunk's config.

---

## 7. Minimal Changeset

### New file

| File | Purpose |
|---|---|
| `orchestrator.py` | Splits cases, generates chunk configs, launches subprocesses, waits, merges results |

### Modified files

| File | Change |
|---|---|
| `runner.py` | Add `--workers` argument. If `workers > 1`, delegate to `orchestrator.run_parallel()` instead of `run_ablation_mode()`. If `workers == 1`, existing serial path unchanged. |

### Untouched files

Everything else: `execution.py`, `execution_v2.py`, `parser_v2.py`, `logging_core.py`,
`live_metrics.py`, `call_logger.py`, `llm.py`, `contracts_v2.py`, `reasoning_v2.py`,
`evaluator_v2.py`, `metrics_v2.py`, all test files, all prompt templates, all configs.

The execution pipeline is completely unmodified. Workers run the same `runner.py main()`
entry point that exists today.

---

## 8. Rollout Plan

### Stage 0 — Dry run validation

- The orchestrator generates chunk configs and case files but does NOT launch
  subprocesses.
- Validates: all cases covered, no duplicates, configs are valid YAML, case files
  parse correctly.
- **Success criteria:** All chunks account for all 58 cases exactly once. Each chunk
  config passes `load_config()` validation.
- **Failure signal:** Duplicate or missing cases.
- **Rollback:** Fix the splitting logic.

### Stage 1 — Small parallel test (5 cases, 2 workers)

- Run 5 cases split into 2 chunks (3 + 2 cases).
- Compare merged output against a serial run of the same 5 cases.
- **Success criteria:**
  - Same number of events (15 per run).
  - Same (case_id, condition) pairs in both.
  - Same `pass` values (modulo API non-determinism — at most 1-2 differences).
  - Merged `events.jsonl` is valid JSONL with monotonic event_ids.
  - No missing events, no duplicates.
  - Wall-clock time < serial time.
- **Failure signal:** Missing events, corrupt JSONL, event count mismatch.
- **Rollback:** Disable parallel, investigate merge logic.

### Stage 2 — Partial ablation (19 parse-failure cases, 4 workers)

- Run the 19 parse-failure cases with gpt-4.1-nano, 4 workers.
- Verify three-tier parse diagnostics are correctly logged in merged output.
- **Success criteria:** All 57 expected events present. `v2_parse_tiers` populated
  in all `run.jsonl` entries. Merge completes without errors.
- **Failure signal:** Missing events, corrupt merge, `v2_parse_tiers` data lost.
- **Rollback:** Fall back to serial execution for the full ablation.

### Stage 3 — Full ablation (58 cases, 4 workers, all 3 models)

- Run the complete v2 ablation for all models.
- Compare pass rates against the serial runs (expect identical within API noise).
- **Success criteria:** 174 events per model. Pass rates within 3pp of serial runs.
  All analysis scripts work on the merged output.
- **Failure signal:** Systematic pass rate deviation (>5pp), missing events.
- **Rollback:** Use serial runs as authoritative results.

---

## 9. Risk Analysis

### Risk 1: Events.jsonl corruption during merge

**Cause:** Bug in the merge logic writes partial lines or invalid JSON.
**Mitigation:** The merge writes to a NEW file (not appending to an existing one).
It validates every line with `json.loads()` after writing. The chunk-level files
are preserved as backup. If merge validation fails, the chunk files are the
ground truth.

### Risk 2: Dropped events (case executed but no event)

**Cause:** Worker crashes between API call completion and event write.
**Mitigation:** Events are flushed after every write. The gap between "API returned"
and "event flushed" is microseconds (JSON serialization + file.write + flush).
The merge validation checks for missing (case_id, condition) pairs and flags them.
Dropped events are detectable and documented, not silent.

### Risk 3: Duplicate execution (case run by two workers)

**Cause:** Bug in case splitting assigns the same case to two chunks.
**Mitigation:** The splitting function is trivial (list slicing). Stage 0 dry run
validates no duplicates. The merge validation checks for duplicate (case_id, condition)
pairs. If found, the merge fails loudly rather than silently including both.

### Risk 4: Inconsistent run_id across workers

**Cause:** Each worker config must share the same run_id for the merged output to be
a single logical run.
**Mitigation:** The orchestrator generates all chunk configs from a single template.
The run_id is set once and copied to all chunks. The merge validates that all events
carry the same run_id.

### Risk 5: OpenAI rate limiting under parallel load

**Cause:** 4 workers making concurrent API calls exceed the account's RPM limit.
**Mitigation:** At 4 workers x ~2 calls/pair x ~3 pairs/min/worker = ~24 RPM,
well under typical limits (500+ RPM). The OpenAI SDK has built-in retry with
exponential backoff for 429 responses. If rate limiting occurs, workers slow down
independently — no coordination needed.

### Risk 6: call_id collision in merged calls/ directory

**Cause:** Each worker assigns call_ids starting from 1. Merging `calls/000001.json`
from two workers would overwrite.
**Mitigation:** The merge renames call files with a chunk prefix:
`calls/000001.json` from chunk_0 becomes `calls/c0_000001.json`. The
`calls_index.json` is rebuilt from the merged events with updated paths.

### Risk 7: Partial worker failure leaves inconsistent state

**Cause:** Worker 2 crashes, workers 0/1/3 complete. Merged output has 44/58 cases.
**Mitigation:** The orchestrator emits a clear summary: "3/4 chunks completed.
14 cases from chunk_2 are incomplete." The merged output marks these cases as
missing. The user can re-run chunk_2's config with `--resume` and then re-merge.

---

## 10. Final Design Decision

**Process-per-chunk with per-worker WAL and post-hoc merge.**

- Orchestrator splits cases into N chunks (default 4).
- Each chunk runs as a separate `runner.py` subprocess.
- Each subprocess writes to its own directory using the existing, unmodified pipeline.
- After all subprocesses complete, the orchestrator merges the per-chunk outputs
  into a single run directory.
- Merge is deterministic, validated, and preserves all event ordering and integrity
  guarantees.
- The execution pipeline code (`execution.py`, `execution_v2.py`, `parser_v2.py`,
  `logging_core.py`, etc.) is completely untouched.
- One new file: `orchestrator.py` (~200 lines).
- One small change to `runner.py`: if `workers > 1`, delegate to orchestrator.
