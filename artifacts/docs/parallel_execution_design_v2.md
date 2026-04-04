# Parallel Execution Design v2 (Corrected)

This supersedes `parallel_execution_design.md`. All 9 critical issues are addressed.

---

## 1. Execution Model

Unchanged from v1. Summary:

**Unit of parallelization:** One subprocess per disjoint case-file chunk. Each
subprocess gets a subset of cases and runs ALL conditions for those cases serially.

**Why safe:** Each `(case_id, condition)` unit reads only immutable inputs (case JSON,
prompt templates, config) and writes only to its own logger. No unit reads another
unit's output. The execution pipeline code is completely unmodified inside each worker.

**Job creation:** Orchestrator splits the full case list into N disjoint chunks via
list slicing. Each chunk is written to a temporary case file. Each chunk gets its
own YAML config pointing to its case file and a unique sub-run directory within the
parent run directory.

**Job scheduling:** All N processes launched simultaneously via `subprocess.Popen`.
Orchestrator waits for all to complete. Fixed assignment, no dynamic scheduling.

---

## 2. Process Model

### Workers

Default `max_workers = 4`, configurable in the YAML config under `execution.max_workers`.

Each worker is a separate `runner.py` invocation:

```
.venv/bin/python runner.py --config {tmp}/chunk_{i}.yaml
```

Each worker creates its own `RunLogger`, its own output directory, its own OpenAI
client. Zero shared mutable state between workers.

### Worker lifecycle

1. Orchestrator loads config, loads cases, validates, splits into N chunks.
2. Writes N chunk configs + case files. Each config has:
   - Same `run_id`, `model`, `trial`, `conditions` as the parent config.
   - Unique `run_dir`: `{parent_run_dir}/chunk_{i}/`
   - `cases.source`: path to the chunk's case file.
   - `chunk_id`: `"chunk_{i}"` (new field, carried into events).
3. Launches N subprocesses.
4. Waits for all to complete (blocking poll with per-worker timeout).
5. Checks exit codes. Captures stderr for failed workers.
6. Runs merge.
7. Cleans up temp configs/case files (chunk output directories are preserved).

### Worker crash

- Orchestrator records the failure (exit code, stderr) in `merge_report.json`.
- Orchestrator does NOT retry.
- Partial results from the crashed worker's directory are preserved. All events
  written before the crash are valid (WAL property).
- Other workers are unaffected.
- The merge proceeds with available chunks, marking the failed chunk's cases as
  incomplete.

---

## 3. Logging Architecture

### Decision: Per-worker WAL, read-only merge

Each worker writes to its OWN `events.jsonl`, `run.jsonl`, and `calls/` directory.
The orchestrator produces a merged view by READING these files. Worker WAL files
are NEVER modified after the worker exits.

### Write mechanism per worker

**Unchanged.** Each worker uses the existing `RunLogger` exactly as the serial path:
- `events.jsonl`: `file.write() + flush()`, conditional `fsync()`
- `run.jsonl`: `os.open/os.write/os.fsync/os.close` per event
- `calls/`: `write_json_atomic()` (temp + fsync + rename)

No new write mechanisms. No locking. No coordination.

### WAL immutability guarantee

After a worker process exits (success or crash), the orchestrator NEVER writes to,
modifies, or appends to any file in that worker's output directory. The per-chunk
WAL files are permanent ground truth.

The merged output is a DERIVED ARTIFACT produced by reading chunk WALs. If the
merge is ever questioned, the chunk WALs are authoritative.

---

## 4. Merge Algorithm

### 4.1 Input

```
{parent_run_dir}/
  chunk_0/events.jsonl, run.jsonl, calls/, calls_flat/
  chunk_1/events.jsonl, run.jsonl, calls/, calls_flat/
  ...
  chunk_{N-1}/...
```

### 4.2 JSONL validation (per chunk)

For each chunk's `events.jsonl`:

1. Read file line by line.
2. For each line, attempt `json.loads()`.
3. If a line fails to parse:
   - If it is the LAST line of the file: discard it (truncated write from crash).
     Record in `merge_report.json`: `{"chunk": i, "discarded_trailing_line": true, "line_number": N}`.
   - If it is NOT the last line: the WAL is structurally corrupt. Mark the entire
     chunk as `"corrupt"` in `merge_report.json`. Exclude this chunk from the merge.
     Do NOT attempt partial recovery.
4. Valid events are collected into a list with `chunk_id` annotated on each event
   (read from the event's payload, or inferred from directory name).

Same validation applied to `run.jsonl`.

### 4.3 Merge events.jsonl

**Rule: event_id is NEVER rewritten.**

Each event retains its original `event_id` as assigned by its worker's `RunLogger`.
The `event_id` field represents LOCAL causal ordering within a single worker. It is
NOT a global sequence number.

The merged `events.jsonl` is produced by:

1. Collect all validated events from all chunks into one list.
2. Annotate each event with `chunk_id` (if not already present).
3. Sort by `(timestamp, chunk_id, event_id)`.
   - `timestamp`: ISO 8601 string, lexicographic sort.
   - `chunk_id`: string sort (e.g., "chunk_0" < "chunk_1").
   - `event_id`: integer sort (local ordering within chunk).
4. Assign a NEW field `global_event_index` (integer, 1-based, monotonically increasing)
   to each event in the sorted list. This is an ADDITIVE field — it does not replace
   `event_id`.
5. Write the sorted events to `{parent_run_dir}/events.jsonl`.

**Cross-process ordering caveat:** The sort order `(timestamp, chunk_id, event_id)` is
deterministic but NOT causally meaningful across chunks. Two events from different
chunks with similar timestamps have no causal relationship. The ordering exists only
to produce a stable, reproducible merged file. Within a single chunk, the `event_id`
ordering IS causal.

### 4.4 Merge run.jsonl

1. Read all validated entries from all chunks' `run.jsonl` files.
2. Annotate each entry with `chunk_id`.
3. Sort by `(timestamp, chunk_id)`.
4. Write to `{parent_run_dir}/run.jsonl`.

No field rewriting. Entries are copied verbatim with `chunk_id` added.

### 4.5 Merge calls/ directory

Each chunk has local call_ids starting from 1: `calls/000001.json`, `calls/000002.json`, etc.

**Renaming scheme:**
- File `chunk_{i}/calls/{local_id}.json` is copied to `{parent}/calls/c{i}_{local_id}.json`.
- File `chunk_{i}/calls_flat/{local_id}_{phase}.txt` is copied to `{parent}/calls_flat/c{i}_{local_id}_{phase}.txt`.

**Reference fixup:**

A `call_path_map.json` is written to `{parent_run_dir}/`:

```json
{
  "chunk_0/calls/000001.json": "calls/c0_000001.json",
  "chunk_0/calls/000002.json": "calls/c0_000002.json",
  ...
}
```

This map enables any consumer to resolve references from the per-chunk events to the
merged calls directory. The events themselves are NOT modified — their `call_id` fields
remain local. The mapping is external.

A merged `calls_index.json` is built by:
1. Reading each chunk's `calls_index.json` (if present).
2. Rewriting the `json` and `flat` path fields using the renaming scheme.
3. Adding `chunk_id` to each entry.
4. Writing the combined index to `{parent}/calls_index.json`.

### 4.6 Produce merge_report.json

Written to `{parent_run_dir}/merge_report.json`. Contains:

```json
{
  "merge_timestamp": "2026-03-30T...",
  "chunks": [
    {
      "chunk_id": "chunk_0",
      "status": "complete",
      "events_count": 45,
      "run_entries_count": 15,
      "calls_count": 30,
      "discarded_trailing_lines": 0
    },
    {
      "chunk_id": "chunk_2",
      "status": "failed",
      "exit_code": 1,
      "stderr_tail": "...",
      "events_count": 12,
      "expected_cases": ["case_a", "case_b", ...],
      "completed_cases": ["case_a"],
      "incomplete_cases": ["case_b", ...]
    }
  ],
  "expected_pairs": [["case_id", "condition"], ...],
  "completed_pairs": [["case_id", "condition"], ...],
  "missing_pairs": [["case_id", "condition"], ...],
  "duplicate_pairs": [],
  "corrupt_chunks": [],
  "total_events_merged": 150,
  "total_run_entries_merged": 50,
  "total_calls_merged": 100
}
```

**No synthetic events.** Missing cases are documented in `merge_report.json` ONLY.
The WAL files contain only events actually emitted by the pipeline.

### 4.7 Derive metrics.json

Read merged `events.jsonl`. Count `case.end` events where `payload.pass == True`.
Write to `{parent}/metrics.json`. Standard format, compatible with existing analysis.

---

## 5. Failure + Recovery Model

### What is guaranteed written after a successful `_run_one()` call

For a single `(case_id, condition)` execution that completes (success or caught failure):
- `case.start` event in `events.jsonl` (emitted at entry to `_run_one()`)
- One or more `generation`/`classification` call events (emitted per API call)
- `case.end` event (normal completion) OR `case.failed` event (caught exception)
- One entry in `run.jsonl` (emitted by `logger.log_run()`)
- Call files in `calls/` (one per API call, written atomically)

All events are flushed before the next `_run_one()` call begins. Within a worker,
events are strictly sequential.

### What may be missing after a worker crash

If the worker process is killed (SIGKILL, OOM, etc.) mid-execution:
- The last `case.start` may exist without a matching `case.end`/`case.failed`.
- The last API call's response may be lost (call completed but event not flushed).
- All PRIOR cases in that worker are complete and valid (WAL property).

### How missing data is detected

The merge validation (section 8) compares expected `(case_id, condition)` pairs against
actual terminal events (`case.end` or `case.failed`). Any pair with a `case.start` but
no terminal event is listed in `merge_report.json` under `incomplete_cases` for that
chunk. Any pair with no events at all is listed under `missing_pairs`.

### No silent data loss

Every failure mode produces observable evidence:
- Worker crash: non-zero exit code + incomplete event sequence in WAL.
- API failure: `case.failed` event with structured error.
- Parse failure: `case.end` event with `parser_failure_v2` category.
- Merge detects all discrepancies and records them in `merge_report.json`.

There is no path where work is lost without a record of the loss.

---

## 6. Resume Semantics

### Authoritative resume source

**Merged `events.jsonl` ONLY.** The existing `load_completed_pairs()` function reads
`events.jsonl` and returns `(case_id, condition)` pairs that have terminal events. This
function works identically on merged output because the merged file is standard JSONL
with the same event schema.

### Resume after partial parallel run

If chunks 0, 1, 3 completed but chunk 2 failed:

1. The merge produces a merged `events.jsonl` containing events from chunks 0, 1, 3.
   Chunk 2's completed cases (before crash) are also included.
2. `merge_report.json` lists the missing pairs.
3. To resume: run the orchestrator again with the same config and `--resume {run_dir}`.
4. The orchestrator calls `load_completed_pairs()` on the merged `events.jsonl` to
   get the skip set.
5. It splits ONLY the remaining cases into chunks and launches workers for them.
6. After new workers complete, a new merge is performed: the existing merged
   `events.jsonl` is treated as "chunk_existing" and the new chunk outputs are merged
   with it.

### Guarantees

- No duplicate execution: `load_completed_pairs()` returns ALL completed pairs from
  the merged WAL. Workers skip any pair in this set.
- No missing coverage: the orchestrator computes `expected_pairs - completed_pairs`
  and creates chunks only for the remaining pairs.
- Resume produces the same final output as if the run had succeeded on the first attempt
  (modulo API non-determinism between the original and resumed calls).

---

## 7. Calls/ Consistency Handling

### Problem

Each worker assigns local `call_id` values starting from 1. Events in each worker's
`events.jsonl` reference these local IDs (e.g., `"call_id": 3`). After merge, the
calls directory uses renamed files (`c0_000003.json`).

### Solution: external mapping, no event modification

1. Per-chunk call files are renamed to `c{chunk_index}_{local_id:06d}.json` in the
   merged `calls/` directory.

2. A `call_path_map.json` file provides the mapping:
   ```
   "chunk_0/000003" -> "c0_000003"
   ```

3. Events in the merged `events.jsonl` retain their original `call_id` values AND
   their `chunk_id` annotation. Any consumer can resolve a call reference by:
   ```
   chunk_id + call_id -> call_path_map -> merged file path
   ```

4. The merged `calls_index.json` has already-resolved paths (using the renamed
   filenames) plus `chunk_id` for each entry. This is the primary lookup table.

5. Per-chunk `calls/` directories are preserved intact in `chunk_{i}/calls/`.
   They can be used directly without the mapping.

### No modification of WAL events

Events are NEVER modified to update call paths. The mapping is external. This
preserves WAL immutability.

---

## 8. Validation Layer

### Pre-merge validation (per chunk)

For each chunk directory:

1. **JSONL integrity:** Every line of `events.jsonl` and `run.jsonl` parses as valid JSON.
   Truncated trailing line is discarded and logged. Non-trailing corrupt line marks
   chunk as corrupt.

2. **Event sequence:** `event_id` values are monotonically increasing (no gaps allowed
   within a chunk; gaps indicate lost events).

3. **Terminal event matching:** Every `case.start` has a matching `case.end` or
   `case.failed` with the same `trace_id`. Unmatched starts are logged as incomplete.

4. **run_id consistency:** All events in the chunk carry the expected `run_id`.

### Post-merge validation

After producing the merged output:

1. **Completeness check:**
   - Compute expected pairs: `{(case_id, condition) for case in cases for condition in conditions}`
   - Compute completed pairs: `{(e["case_id"], e["condition"]) for e in events if e["event_type"] in ("case.end", "case.failed")}`
   - `missing_pairs = expected - completed`
   - `duplicate_pairs = {pair for pair in completed if count > 1}`
   - If `duplicate_pairs` is non-empty: merge FAILS. This indicates a case-splitting
     bug. The merge output is NOT written. The chunk files are the only valid data.
   - If `missing_pairs` is non-empty: merge SUCCEEDS with warnings. Missing pairs are
     documented in `merge_report.json`.

2. **JSONL re-validation:** Every line of the merged `events.jsonl` is re-parsed after
   writing to confirm no corruption during merge.

3. **Call file existence:** For every call event in the merged events, the corresponding
   file exists in the merged `calls/` directory (via `call_path_map`).

4. **Metric consistency:** `metrics.json` pass count matches manual count from events.

### Merge failure behavior

If validation fails on duplicates or corruption:
- Merged output files are NOT written (or are deleted if partially written).
- `merge_report.json` is still written with the failure details.
- Chunk directories are preserved as ground truth.
- The orchestrator exits with non-zero status and prints the failure reason.

---

## 9. Rate Limiting Strategy

### Configuration

```yaml
execution:
  max_workers: 4
  worker_stagger_seconds: 5
```

### Staggered start

Workers are launched with a fixed delay between them:

```
launch chunk_0 at T+0s
launch chunk_1 at T+5s
launch chunk_2 at T+10s
launch chunk_3 at T+15s
```

This prevents a burst of simultaneous API calls at startup. After the initial stagger,
workers naturally desynchronize due to varying response times.

### Per-model concurrency

The `max_workers` setting applies per orchestrator invocation. If the user runs two
orchestrators simultaneously (one for nano, one for 4o-mini), they share the same
API key and rate limit. The user is responsible for not launching more concurrent
orchestrators than their rate limit supports.

Practical guideline documented in the config:
- 2-4 workers for accounts with 500 RPM limit
- 4-8 workers for accounts with 3500+ RPM limit

### Backpressure

No explicit backpressure mechanism. The OpenAI SDK's built-in retry with exponential
backoff handles 429 responses per-worker. If sustained rate limiting occurs, each
worker independently slows down. This is sufficient because:
- Workers are independent processes — one worker's backoff does not affect others.
- The SDK retries are deterministic and logged.
- Total RPM at 4 workers is ~24, well under typical limits.

If a worker repeatedly hits rate limits and exhausts retries, the API call fails,
`_run_one()` catches the exception, and `logger.fail_case()` emits a structured
error event. The case is not silently dropped.

---

## 10. Final Guarantees

### What the system guarantees after this design

1. **WAL immutability:** Per-chunk `events.jsonl` files are NEVER modified after the
   worker exits. They are permanent ground truth.

2. **No fabricated events:** The merged `events.jsonl` contains ONLY events that were
   actually emitted by the pipeline. No synthetic events are ever injected.

3. **No event_id corruption:** Original `event_id` values are preserved verbatim.
   `global_event_index` is additive, not a replacement.

4. **No silent data loss:** Every missing case, incomplete execution, corrupt chunk,
   and discarded line is documented in `merge_report.json`.

5. **Deterministic merge:** Same set of chunk WALs always produces the same merged
   output, regardless of when or how many times the merge is run.

6. **Backward compatibility:** The merged output directory has the same structure as
   a serial run (`events.jsonl`, `run.jsonl`, `calls/`, `metrics.json`). Existing
   analysis scripts work without modification.

7. **Resume correctness:** `load_completed_pairs()` on merged `events.jsonl` returns
   all completed pairs. Resume skips these and runs only the remainder.

8. **Call traceability:** Every call event can be resolved to its call file via
   `(chunk_id, call_id) -> call_path_map -> file path`. No dangling references.

9. **Failure observability:** Worker crashes, API failures, parse failures, and merge
   anomalies all produce structured, queryable records. Nothing is silent.

---

## Changeset

| File | Change |
|---|---|
| `orchestrator.py` | NEW. ~250 lines. Case splitting, config generation, subprocess launch, merge, validation. |
| `runner.py` | Add `max_workers` config field handling. If > 1, delegate to `orchestrator.run_parallel()`. Serial path unchanged. |
| `experiment_config.py` | Add `execution.max_workers` (default 1) and `execution.worker_stagger_seconds` (default 5) to config schema. |
| All other files | UNTOUCHED. |

---

## Rollout Plan

Unchanged from v1: Stage 0 (dry run), Stage 1 (5 cases / 2 workers), Stage 2
(19 cases / 4 workers), Stage 3 (full ablation). Success criteria and rollback
conditions as previously defined.

Additional criterion for Stage 1: verify `merge_report.json` has zero missing pairs,
zero duplicates, zero corrupt chunks. Verify `global_event_index` is monotonic.
Verify `event_id` values in merged file match originals in chunk files.
