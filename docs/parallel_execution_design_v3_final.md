# Parallel Execution Design v3 (Final Corrected)

This is the final design. It supersedes v1 and v2. It fixes the 10 remaining
correctness issues identified in the v2 audit.

The core architecture is unchanged: process-per-chunk with per-worker WAL and
read-only merge. This document specifies ONLY the corrected invariants, policies,
and procedures.

---

## 1. Corrected Invariants

### Per-chunk event_id invariant

Within a single chunk's `events.jsonl`:

- `event_id` values MUST be strictly increasing: for any two consecutive events
  A and B where A appears before B in the file, `A.event_id < B.event_id`.
- Gaps ARE allowed. A sequence like `[1, 2, 5, 6]` is valid. This occurs when
  the `RunLogger` allocates an `event_id` (incrementing its counter), but the
  process crashes before the event is flushed. The counter advanced but the write
  did not complete. The gap is evidence of a crash, not corruption.
- Duplicates are FORBIDDEN. Two events with the same `event_id` within one chunk
  indicate a logger bug (counter was not incremented). This is a hard failure.
- Decreases are FORBIDDEN. An `event_id` that is less than or equal to a preceding
  `event_id` indicates file corruption or out-of-order writes. This is a hard failure.

### Why gaps are valid

The `RunLogger._write_event()` method increments `_event_counter` BEFORE writing.
If the process is killed between the increment and the `file.write() + flush()`,
the counter value is lost. The next event (if the process survived, which it did not)
would have used `_event_counter + 1`, skipping the lost value. Since the process
crashed, no next event exists — but if partial events were written for prior cases,
the gap is visible in the surviving prefix.

### Why duplicates and decreases are invalid

The counter is monotonic and single-threaded within each worker. Duplicates require
the counter to not advance between two successful writes — impossible given the
`self._event_counter += 1` before every write. Decreases require the counter to
go backwards — impossible without memory corruption.

---

## 2. Per-Chunk Validation Rules

Applied to each chunk's `events.jsonl` before merge. Each rule produces either
PASS, WARNING, or HARD_FAIL.

| Rule | Check | Outcome |
|---|---|---|
| V1: JSONL prefix integrity | Read lines sequentially. Stop at first unparseable line. | See section 4 for full policy. |
| V2: event_id strictly increasing | For consecutive events i, j: `j.event_id > i.event_id` | HARD_FAIL if decrease or duplicate. WARNING if gap. |
| V3: run_id consistency | All events carry the expected `run_id` from the chunk config. | HARD_FAIL if any event has wrong `run_id`. |
| V4: terminal event uniqueness | For each `(case_id, condition)` within the chunk, at most one terminal event (`case.end` or `case.failed`). | HARD_FAIL if more than one terminal. See section 5. |
| V5: terminal event completeness | Every `case.start` has a matching terminal event with same `trace_id`. | WARNING if unmatched (crash truncation). |
| V6: call file existence | For every call event, the referenced `calls/{call_id:06d}.json` exists. | WARNING if missing (crash during atomic write). |

**Validation result per chunk:** `"valid"` if all rules PASS or WARNING. `"invalid"` if
any rule is HARD_FAIL. Invalid chunks are excluded from the merge.

---

## 3. Merge Ordering Specification

### Sort key

```
(timestamp_str, chunk_id_str, event_id_int)
```

### Timestamp parsing

- The `timestamp` field is an ISO 8601 string produced by `datetime.now().isoformat()`.
- Format: `YYYY-MM-DDTHH:MM:SS.ffffff` (microsecond precision).
- Comparison: lexicographic string comparison. This is correct for ISO 8601 because
  the format is fixed-width and zero-padded.
- No timezone conversion. All workers run on the same machine with the same system
  clock. Timestamps are local time.

### Tie handling

If two events have identical timestamps (same microsecond):
- `chunk_id` breaks the tie. `"chunk_0" < "chunk_1"` (lexicographic).
- If same chunk (impossible across chunks, but within a chunk's events):
  `event_id` breaks the tie (integer comparison, always unique within a chunk).

### Determinism

The sort is fully deterministic: given the same set of input events, the output
order is always identical. Python's `sorted()` with this tuple key is stable.

### Causality statement

The merged order is deterministic and reproducible. It is NOT cross-chunk causal
order. Two events from different chunks at similar timestamps have no causal
relationship. The ordering exists solely to produce a stable, reproducible merged
file that is compatible with sequential-consumption tools.

Within a single chunk, the `event_id` ordering IS causal: event A with
`event_id < event_id_B` happened-before event B.

### global_event_index

After sorting, each event is assigned `global_event_index` = 1, 2, 3, ... This
is a NEW additive field. It provides a single-integer lookup for position in the
merged file. It does NOT replace `event_id`. It has no causal meaning.

---

## 4. JSONL Corruption Recovery Policy

### Principle: prefix-preserving recovery

A JSONL file is read line-by-line from the beginning. Processing stops at the first
line that fails `json.loads()`. All lines before the failure point are the valid
prefix. Everything at and after the failure point is discarded.

### Procedure

```
valid_events = []
for line_number, line in enumerate(file_lines, 1):
    line = line.strip()
    if not line:
        continue  # skip blank lines
    try:
        event = json.loads(line)
        valid_events.append(event)
    except (json.JSONDecodeError, ValueError):
        # Stop here. This line and all subsequent lines are discarded.
        record corruption:
            corrupt_line_number = line_number
            total_lines = len(file_lines)
            is_trailing = (line_number == total_lines)
            lines_discarded = total_lines - line_number + 1
        break
```

### Classification

| Condition | Classification | Merge behavior |
|---|---|---|
| All lines parse | `intact` | Use all events |
| Only the last line fails | `trailing_truncation` | Use valid prefix. WARNING. |
| A non-last line fails | `mid_file_corruption` | Use valid prefix. WARNING. |
| No lines parse | `empty_or_fully_corrupt` | Exclude chunk. WARNING. |

### Key change from v2

v2 discarded the entire chunk on mid-file corruption. v3 preserves the valid prefix.
The valid prefix contains durable, flushed events that completed before the corruption
point. Discarding them would be data loss.

### What is recorded in merge_report.json

```json
{
  "chunk_id": "chunk_2",
  "jsonl_status": "mid_file_corruption",
  "valid_events": 37,
  "corrupt_line_number": 38,
  "total_lines": 45,
  "lines_discarded": 8
}
```

---

## 5. Terminal Event Consistency Rules

### Definition

A terminal event for `(case_id, condition)` is an event with:
- `event_type` equal to `"case.end"` or `"case.failed"`
- matching `case_id` and `condition` fields

### Per-chunk invariant

For each unique `(case_id, condition)` within a chunk's valid event prefix:
- Zero terminal events: the case is **incomplete** (worker crashed mid-case). WARNING.
- Exactly one terminal event: the case is **complete**. PASS.
- More than one terminal event: HARD_FAIL. This indicates a pipeline bug
  (case was evaluated twice within a single worker). The chunk is marked invalid.

### Why both `case.end` and `case.failed` cannot coexist

Within `_run_one()`, execution takes exactly one path:
- Normal return: `logger.end_case()` emits `case.end`. Function returns.
- Exception: `logger.fail_case()` emits `case.failed`. Exception re-raised.

Both paths are mutually exclusive. The `try/except` in `_run_one()` guarantees
exactly one terminal emission per call. If both exist for the same
`(case_id, condition)`, the pipeline has a bug.

### Post-merge invariant

After merging all chunks:
- For each expected `(case_id, condition)` pair:
  - Zero terminal events: listed in `missing_pairs`. WARNING.
  - Exactly one terminal event: PASS.
  - More than one terminal event: HARD_FAIL. Merge is aborted.

Duplicate terminals across chunks indicate a case-splitting bug (same case assigned
to two chunks). This is a hard failure because the two executions may have produced
different results, and there is no valid way to choose between them.

---

## 6. Canonical Call Artifact Resolution

### Decision: `calls_index.json` is the SOLE authoritative lookup

`call_path_map.json` is ELIMINATED. It was redundant with `calls_index.json` and
created source-of-truth confusion.

### `calls_index.json` specification

Each entry:

```json
{
  "call_id": 3,
  "chunk_id": "chunk_0",
  "case_id": "alias_config_a",
  "trace_id": "abc123...",
  "phase": "generation",
  "condition": "baseline_v2",
  "json_path": "calls/c0_000003.json",
  "flat_path": "calls_flat/c0_000003_generation.txt"
}
```

### Resolution contract

A consumer holding an event with `chunk_id` and `call_id` resolves the call artifact
by looking up the entry in `calls_index.json` where `chunk_id` and `call_id` match.
The `json_path` field gives the relative path from the parent run directory.

### Per-chunk fallback

If `calls_index.json` is unavailable (merge did not complete), the consumer can
resolve directly from the chunk directory: `chunk_{i}/calls/{call_id:06d}.json`.
Per-chunk directories are always preserved and self-consistent.

### Why one source, not two

Two overlapping lookup mechanisms (`calls_index.json` and `call_path_map.json`) create
ambiguity: if they disagree, which is correct? A single authoritative index eliminates
this class of bug entirely.

---

## 7. Resume Conflict Policy

### The problem

A resumed run may produce a terminal event for a `(case_id, condition)` pair that
already has a terminal event in the existing merged WAL.

### Policy: REJECT DUPLICATE, ABORT MERGE

If the merge step detects a `(case_id, condition)` pair with terminal events from
BOTH the existing merged WAL and a new chunk, the merge ABORTS with HARD_FAIL.

### Justification

Duplicate execution means the same case was run twice with potentially different
API responses. The two results may differ (different code, different pass/fail).
There is no principled way to choose between them. Accepting either silently
would introduce ambiguity into the research data.

### Prevention

The orchestrator prevents this by construction:
1. Before launching resumed workers, it calls `load_completed_pairs()` on the
   existing merged WAL.
2. It creates chunk configs containing ONLY cases NOT in the completed set.
3. Each worker receives a case list that is disjoint from the completed set.

If prevention fails (bug in orchestrator), the merge validation catches it and
aborts. The existing merged WAL is not overwritten. The new chunk WALs are
preserved for investigation.

### Recovery from conflict

The user must manually investigate which chunk's result to keep, delete the
duplicate chunk, and re-run the merge.

---

## 8. Run Health Classification

### Classification in merge_report.json

```json
{
  "run_health": "healthy" | "degraded" | "failed",
  "health_reason": "..."
}
```

### Criteria

| Status | Criteria |
|---|---|
| `healthy` | All chunks valid. Zero missing pairs. Zero duplicate terminals. Zero corrupt chunks. All call files resolve. |
| `degraded` | All validations pass (no HARD_FAIL), BUT: one or more missing pairs (incomplete worker), OR one or more chunks with trailing truncation, OR one or more chunks with mid-file corruption (valid prefix preserved). Merged output IS produced. |
| `failed` | Any HARD_FAIL condition: duplicate terminal events, event_id decrease/duplicate, run_id mismatch, resume conflict. Merged output is NOT produced. |

### Which statuses produce merged output

- `healthy`: merged output produced.
- `degraded`: merged output produced. `merge_report.json` documents all issues.
  The merged output is usable but incomplete.
- `failed`: merged output NOT produced. Chunk WALs are the only valid data.
  `merge_report.json` is still written (it documents why the merge failed).

---

## 9. Hard-Fail vs Warning Matrix

| Condition | Classification | Merge produced? | Action |
|---|---|---|---|
| Duplicate terminal event for same `(case_id, condition)` | HARD_FAIL | No | Abort merge. Investigate case-splitting or resume bug. |
| event_id decrease within chunk | HARD_FAIL | No | Chunk is corrupt. Exclude and investigate. |
| event_id duplicate within chunk | HARD_FAIL | No | Chunk is corrupt. Exclude and investigate. |
| run_id mismatch in event | HARD_FAIL | No | Wrong chunk included. Exclude. |
| Resume conflict (duplicate terminal across old + new WAL) | HARD_FAIL | No | Abort. Manual resolution required. |
| Missing `(case_id, condition)` pair | WARNING | Yes (degraded) | Document in merge_report. Resumable. |
| Unmatched `case.start` (no terminal) | WARNING | Yes (degraded) | Worker crashed mid-case. Document. |
| Trailing line truncation | WARNING | Yes (degraded) | Discard trailing line. Document. |
| Mid-file corruption (valid prefix preserved) | WARNING | Yes (degraded) | Use valid prefix. Document. |
| event_id gap | WARNING | Yes | Evidence of allocated-but-not-written event. Document. |
| Missing call file for call event | WARNING | Yes (degraded) | Crash during atomic write. Document. |

---

## 10. Crash-Safe Merge Write Procedure

### Principle

If the merge process itself crashes, the parent run directory must not be left in an
ambiguous state. Chunk WALs must remain intact. A partially-written merged file must
not be mistaken for a complete one.

### Procedure

All merged artifacts are written using the atomic temp-file pattern:

```
For each merged artifact (events.jsonl, run.jsonl, calls_index.json, metrics.json, merge_report.json):

1. Write to a temporary file in the same directory:
   {parent_run_dir}/.tmp_{filename}_{random}

2. Flush the file handle.

3. fsync the file descriptor.

4. Atomic rename: os.replace(tmp_path, final_path)

5. fsync the parent directory (on Linux/macOS: open dir fd, fsync, close).
```

### Ordering of writes

Merged artifacts are written in this order:

1. `merge_report.json` — written FIRST, always, even on HARD_FAIL.
2. `calls/` directory — copy renamed call files.
3. `calls_index.json` — written after all call files are in place.
4. `run.jsonl` — merged run entries.
5. `events.jsonl` — merged event stream.
6. `metrics.json` — derived from merged events, written LAST.

### Why this order

`merge_report.json` first: if the merge crashes at any later step, the report
documents what was attempted and what failed. It is the "crash receipt."

`metrics.json` last: it is derived from `events.jsonl`. Writing it last ensures
it is consistent with the events file. If the merge crashes before `metrics.json`,
the events file is still valid and metrics can be re-derived.

`events.jsonl` near-last: it is the most important merged artifact. By the time
it is written, all call files and the run log are already in place. If the merge
crashes during events.jsonl write, the atomic rename has not occurred, so no
partial events.jsonl exists at the final path.

### Crash during merge: observable state

If the merge process crashes at step K:
- Steps 1 through K-1 have completed (atomic renames are durable).
- Step K has a temp file that was not renamed (visible as `.tmp_*` in the directory).
- Steps K+1 through 6 have not started (no files exist at final paths).
- `merge_report.json` exists (written at step 1) and documents the attempt.
- Chunk WALs are untouched.
- The user can re-run the merge (it is idempotent — same inputs, same outputs).

---

## 11. Authoritative Source-of-Truth Table

| Question | Authoritative source | Fallback |
|---|---|---|
| What events did worker N actually emit? | `chunk_{N}/events.jsonl` | None. This is ground truth. |
| What is the merged event stream? | `{parent}/events.jsonl` | Re-derive from chunk WALs by re-running merge. |
| What cases are complete for resume? | `{parent}/events.jsonl` via `load_completed_pairs()` | Scan chunk WALs individually. |
| What call artifacts exist for event E? | `{parent}/calls_index.json` (lookup by `chunk_id` + `call_id`) | `chunk_{N}/calls/{call_id:06d}.json` directly. |
| What went wrong during merge? | `{parent}/merge_report.json` | None. This is the only record. |
| What is the run's pass rate? | `{parent}/metrics.json` | Re-derive from `{parent}/events.jsonl`. |
| Is the run complete and healthy? | `{parent}/merge_report.json` field `run_health` | Re-run merge validation. |

### Hierarchy

```
GROUND TRUTH (immutable, never modified):
  chunk_{N}/events.jsonl
  chunk_{N}/run.jsonl
  chunk_{N}/calls/*.json

DERIVED ARTIFACTS (reproducible from ground truth):
  {parent}/events.jsonl
  {parent}/run.jsonl
  {parent}/calls/*.json
  {parent}/calls_index.json
  {parent}/metrics.json

MERGE METADATA (written by orchestrator):
  {parent}/merge_report.json
```

If any derived artifact is questioned, it can be deleted and re-derived from ground
truth by re-running the merge. Ground truth files are never deleted, modified, or
appended to by the orchestrator.

---

## 12. Final Correctness Guarantees

1. **WAL purity:** Per-chunk WAL files are NEVER modified, appended to, or deleted
   by the orchestrator. They are permanent, immutable ground truth.

2. **No fabricated events:** Merged `events.jsonl` contains ONLY events read from
   chunk WALs, with two additive fields (`chunk_id`, `global_event_index`). No
   events are synthesized, modified, or deleted.

3. **No event_id corruption:** Original `event_id` values are preserved exactly.
   `global_event_index` is additive. `event_id` retains its local causal meaning.

4. **No silent data loss:** Every discarded line, missing case, incomplete execution,
   corrupt chunk, event_id gap, and unresolved call reference is documented in
   `merge_report.json`. There is no failure mode that leaves no observable trace.

5. **Deterministic merge:** Identical chunk WALs always produce identical merged
   output. The merge is a pure function of its inputs.

6. **Crash safety:** If the merge process crashes, chunk WALs are intact,
   `merge_report.json` documents the attempt, and no partial merged artifacts
   exist at their final paths (atomic rename).

7. **Resume correctness:** `load_completed_pairs()` on merged `events.jsonl` returns
   all completed pairs. Resume creates chunks for remaining pairs only. Duplicate
   execution is prevented by construction and detected by validation.

8. **Call traceability:** `calls_index.json` is the single authoritative lookup.
   Every call event resolves to exactly one artifact file. No dangling references
   unless the worker crashed during atomic file write (documented as WARNING).

9. **Failure observability:** Run health is classified as `healthy`, `degraded`, or
   `failed`. Hard failures abort the merge. Warnings produce merged output with
   documented issues. Nothing is silent.

10. **Backward compatibility:** The merged output directory has the same top-level
    structure as a serial run. Existing analysis scripts work without modification
    on `healthy` and `degraded` runs.
