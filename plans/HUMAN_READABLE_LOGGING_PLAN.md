# Human-Readable Logging System — Design Plan v1

**Date:** 2026-03-26
**Status:** DESIGN ONLY — not approved for implementation
**Author:** Claude (audit mode)

---

## 1. DESIGN GOALS

1. **Human-navigable trace logs** — an operator can `ls` into a run directory, find a specific case/attempt, and read the full prompt, full response, and evaluation result as plain files.
2. **Strictly derived from the WAL** — human logs are a projection of `events.jsonl`. They are never a source of truth. They can be deleted and regenerated without data loss.
3. **Single emission pipeline** — all logging flows through one function. No bypass. No convenience hacks. No "temporary" direct writes.
4. **Idempotent under replay** — replaying the same event produces identical files. Replaying a modified event overwrites deterministically. No duplication. No forking.
5. **Failure-transparent** — if log rendering fails, the WAL write has already succeeded. The failure is logged loudly. Execution continues. The operator is never silently missing data.
6. **Zero execution coupling** — the human log layer does not influence control flow, evaluation decisions, or correctness. It is purely observational.

---

## 2. CURRENT ARCHITECTURE AUDIT

### 2.1 Where events are currently emitted

There are **two independent emission paths** that do not share a single entry point:

| Emission function | Called from | Destination | Prompt included | Response included |
|---|---|---|---|---|
| `_emit_metrics_event()` (execution.py:115-203) | `run_single`, `run_repair_loop`, `run_contract_gated`, `run_leg_reduction`, `_fallback_run`, retry_harness | `events.jsonl` (via `live_metrics.emit_event()`) + Redis stream | **NO** | **NO** |
| `write_log()` (execution.py:1087-1093) → `RunLogger._write_locked()` (execution.py:834-932) | Same callers as above | `run.jsonl`, `run_prompts.jsonl`, `run_responses.jsonl` | **YES** (full text in `run_prompts.jsonl`) | **YES** (full text in `run_responses.jsonl` and `run.jsonl` audit field) |

**This is the central problem.** There are two independent write paths that are called side-by-side at each call site (6 locations in execution.py, 1 in retry_harness.py). They are not coordinated. They have different schemas. They write to different files.

### 2.2 Where full prompts/responses currently exist

| File | Content | Schema |
|---|---|---|
| `run_prompts.jsonl` | Full prompt text per eval | `{run_id, case_id, condition, model, prompt}` |
| `run_responses.jsonl` | Full response text per eval | `{run_id, case_id, condition, model, raw_response}` |
| `run.jsonl` | Detailed record with full response in `audit.raw_model_output` | Nested: `{run_id, case_id, condition, model, model_config, prompt_length, raw_response_length, parsed:{...}, execution:{...}, evaluation:{...}, audit:{...}}` |
| `events.jsonl` | Lightweight metrics only | 14-26 flat fields. **No prompt. No response.** |

### 2.3 Where information is lost

1. **`events.jsonl` has no prompt or response text.** It cannot render human-readable logs on its own. This means the proposed architecture ("human logs are derived from the WAL") cannot work with the current WAL schema. The WAL must be enriched.

2. **`_emit_metrics_event()` discards prompt and response.** The function signature is `(case, model, condition, ev, elapsed_seconds)`. The caller has `prompt` and `raw_output` in local scope at every call site but does not pass them.

3. **`call_model()` returns only the response.** The `full_prompt` (prompt + JSON output instruction) is constructed inside `call_model()` (llm.py:97-103) and never returned. The caller retains the base `prompt` but not the decorated `full_prompt` that was actually sent to the API.

4. **Retry harness logs only the final iteration to `write_log()`.** Per-iteration prompts/responses go to `_write_iteration_log()` (retry_harness.py:943-1002), which writes to the same three files. But only the last iteration's data reaches `_emit_metrics_event()`.

5. **Contract-gated path loses the contract prompt.** `run_contract_gated()` makes 2-3 `call_model()` calls (contract elicitation, code generation, optional retry). Only the code generation prompt/response is passed to `write_log()`. The contract prompt and response are lost.

6. **`_fallback_run()` passes empty string as prompt.** Line 711: `write_log(case["id"], "contract_gated", model, "", contract_raw, parsed, ev)`.

7. **Schema divergence between runs.** The `rerun_gpt-4.1-nano` events have 14 fields. The `stable_gpt-4o-mini` events have 26 fields. The 12 Phase 1 observability fields are missing from older runs. This means replay of older WALs will produce incomplete human logs.

### 2.4 What existing code must change

| Component | Change required |
|---|---|
| `_emit_metrics_event()` | Must accept `prompt` and `raw_output` parameters |
| `events.jsonl` schema | Must include `prompt` and `raw_output` fields |
| `live_metrics.emit_event()` | Must accept and write larger payloads |
| Every call site (7 locations) | Must pass `prompt` and `raw_output` to `_emit_metrics_event()` |
| `call_model()` (llm.py) | Should return `full_prompt` alongside response, OR callers must accept that the base prompt (not the decorated one) is what gets logged |
| `write_log()` / `RunLogger` | Must be **removed or demoted** — it becomes redundant once human logs are derived from the WAL |

### 2.5 Duplicate code paths

**YES — there is already duplication.** `write_log()` and `_emit_metrics_event()` are called side-by-side at 7 locations. They serve overlapping purposes (logging evaluation results) but with different schemas, different destinations, and different completeness. The proposed design must eliminate this duplication by making `write_log()` a derived projection of the WAL, not an independent write path.

---

## 3. REQUIRED INVARIANTS

1. **WAL-first ordering.** The WAL write (`events.jsonl`) MUST succeed before human log rendering begins. If the WAL write fails, no human log is written. If the human log write fails, the WAL write is already durable.
2. **Single emission point.** All logging passes through exactly one function. No caller writes to any log file directly.
3. **Deterministic paths.** Given an event dict, the output file paths are a pure function of `(run_id, model, case_id, attempt_index)`. No randomness. No timestamps in paths.
4. **Idempotent writes.** Writing the same event twice produces identical files. Writing a modified event overwrites the previous version.
5. **No execution coupling.** Human log rendering failures never cause evaluation failures. The `try/except` boundary is explicit and logged.
6. **Schema completeness.** Every event in the WAL contains all data needed to render all four human log files (prompt.txt, response.txt, evaluation.json, metadata.json). If a field is missing, the event is malformed — log a warning, write what you can, do not crash.
7. **Backward compatibility.** Old WALs missing new fields produce degraded human logs (missing files or placeholder content), not crashes.

---

## 4. EVENT SCHEMA AUDIT

### 4.1 Current WAL schema (events.jsonl)

The current schema has 14-26 fields depending on the run. The full union:

```
case_id, model, condition, trial, run_id,
pass, score, reasoning_correct, code_correct,
failure_type, category, num_attempts, elapsed_seconds, timestamp,
code_present, code_empty_reason, code_source, case_validity,
parse_tier, parse_repaired, recovery_applied,
reconstruction_status, reconstruction_recovered, content_normalized,
failure_source, failure_source_detail
```

### 4.2 Fields MISSING from WAL that are required for human logs

| Field | Required for | Currently available where | Action |
|---|---|---|---|
| `prompt` | `prompt.txt` | Local variable in every run_* function; written to `run_prompts.jsonl` by `write_log()` | **ADD to WAL event** |
| `raw_output` | `response.txt` | Local variable in every run_* function; written to `run_responses.jsonl` by `write_log()` | **ADD to WAL event** |
| `attempt_index` | Directory path `attempt_{N}/` | Not tracked explicitly. `num_attempts` exists but is the total count, not the index of this specific event. For non-retry paths, always 0. | **ADD to WAL event** |
| `evaluation` (full dict) | `evaluation.json` | `ev` dict exists at call sites; only selected fields are extracted into current WAL | **ADD to WAL event** (full `ev` dict, not cherry-picked fields) |
| `error_info` | `metadata.json` | Scattered across `ev.get("error_message")`, `parsed.get("parse_error")`, etc. | **ADD structured error field to WAL event** |
| `parsed` (key fields) | `evaluation.json` | Available at call sites in the `parsed` dict | **ADD `parsed_reasoning`, `parsed_code_length`, `response_format`, `parse_error` to WAL event** |

### 4.3 Backward compatibility

Old WAL files will not have `prompt`, `raw_output`, `attempt_index`, or the full `evaluation` dict. The LogRenderer must handle this:

- `prompt.txt`: If `prompt` field is missing, write a placeholder: `[prompt not available — event predates schema v2]`
- `response.txt`: If `raw_output` field is missing, write same placeholder pattern
- `evaluation.json`: If full `evaluation` field is missing, write the subset of fields that do exist (`pass`, `score`, `reasoning_correct`, `code_correct`, etc.)
- `metadata.json`: Always writable from existing fields

### 4.4 Schema version

Add a `_schema_version` field to every WAL event:
- `1` = current events (no prompt/response)
- `2` = enriched events (prompt, raw_output, attempt_index, full evaluation)

The LogRenderer checks this field to decide rendering strategy. Unversioned events are treated as version 1.

### 4.5 WAL size implications

Adding full prompts (~4-8KB) and responses (~2-12KB) to every event will increase `events.jsonl` from ~700 bytes/event to ~10-20KB/event. For 116 events, that's ~1-2MB per run instead of ~80KB. This is acceptable. The per-run prompts/responses files are already this size.

---

## 5. PROPOSED COMPONENTS

### 5.1 Component: `_emit_event()` (unified emission point)

**Location:** `execution.py` (replaces both `_emit_metrics_event()` and `write_log()`)

**Signature:**
```python
def _emit_event(
    case: dict,
    model: str,
    condition: str,
    prompt: str,
    raw_output: str,
    parsed: dict,
    ev: dict,
    attempt_index: int = 0,
    elapsed_seconds: float | None = None,
) -> None:
```

**Responsibilities:**
1. Build the enriched event dict (flat metrics + prompt + response + full eval)
2. Write to WAL via `live_metrics.emit_event()` (durable, fsync'd)
3. Write to Redis stream via `redis_metrics.emit_event()` (best-effort, metrics only — no prompt/response to Redis)
4. Call `LogRenderer.render(event)` to produce human-readable files
5. If LogRenderer fails, log warning, continue

**This replaces:**
- `_emit_metrics_event()` — absorbed entirely
- `write_log()` / `RunLogger._write_locked()` — absorbed entirely. RunLogger becomes dead code and is deleted.

**Call sites that must be updated (7 total):**

| Location | Current calls | New call |
|---|---|---|
| `run_single()` ~line 554-555 | `write_log(...)` then `_emit_metrics_event(...)` | `_emit_event(case, model, condition, prompt, raw_output, parsed, ev, attempt_index=0, elapsed_seconds=...)` |
| `run_repair_loop()` attempt 1 ~line 597-598 | Same pattern | `_emit_event(..., attempt_index=0, ...)` |
| `run_repair_loop()` attempt 2 ~line 611-612 | Same pattern | `_emit_event(..., attempt_index=1, ...)` |
| `run_contract_gated()` ~line 692-693 | Same pattern | `_emit_event(..., attempt_index=0, ...)` |
| `_fallback_run()` ~line 711-712 | Same pattern (empty prompt) | `_emit_event(..., prompt="", ...)` |
| `run_leg_reduction()` ~line 773-774 | Same pattern | `_emit_event(..., attempt_index=0, ...)` |
| `retry_harness` ~line 1528-1530 | Same pattern | `_emit_event(..., attempt_index=last_k, ...)` |

### 5.2 Component: `LogRenderer`

**Location:** New file `log_renderer.py`

**Responsibilities:**
1. Receive a fully-formed event dict
2. Compute output paths deterministically
3. Create directories
4. Write four files per event: `prompt.txt`, `response.txt`, `evaluation.json`, `metadata.json`
5. Handle idempotency (overwrite policy)
6. Handle missing fields gracefully (degrade, don't crash)
7. Sanitize path components

**Public interface:**
```python
class LogRenderer:
    def __init__(self, run_dir: Path):
        """run_dir is the per-run directory (e.g., logs/ablation_runs/stable_gpt-4o-mini_t1_xxx/)"""

    def render(self, event: dict) -> None:
        """Render human-readable log files for one event. Idempotent."""

    @staticmethod
    def compute_path(run_dir: Path, model: str, case_id: str, attempt_index: int) -> Path:
        """Pure function: event identity → directory path."""
```

**No other public methods.** The renderer is a projection function, not a stateful service.

### 5.3 Component: `live_metrics.emit_event()` (modified)

**Current behavior:** Validates required keys, writes JSON line, fsyncs.

**Required change:** Accept and write larger payloads (prompt/response text). No schema change needed for this function — it writes whatever dict it receives. The `REQUIRED_EVENT_KEYS` validation already covers the identity fields. The new fields (`prompt`, `raw_output`, `evaluation`) are optional from `live_metrics`' perspective — the schema enforcement happens in `_emit_event()` before calling `live_metrics`.

**One concern:** The current `live_metrics.emit_event()` writes the full event dict to `events.jsonl`. Adding 10-20KB prompt/response per event makes the file ~100x larger. This is acceptable for correctness but may slow dashboard aggregation. Mitigation: the dashboard reads `events.jsonl` and can skip `prompt`/`raw_output` fields during aggregation (they're not used for metrics computation).

### 5.4 Component: `redis_metrics.emit_event()` (unchanged)

Redis receives metrics only. No prompt/response. No change needed. The `_emit_event()` function extracts metrics fields for Redis separately from the full WAL event.

### 5.5 Component: `RunLogger` (deleted)

`RunLogger` and all its methods (`write`, `_write_locked`, `write_summary`) become dead code. The three files it currently writes (`run.jsonl`, `run_prompts.jsonl`, `run_responses.jsonl`) are replaced by:
- `run.jsonl` → subsumed by enriched `events.jsonl` (same data, one file)
- `run_prompts.jsonl` → subsumed by `logs/{model}/case_{id}/attempt_{n}/prompt.txt`
- `run_responses.jsonl` → subsumed by `logs/{model}/case_{id}/attempt_{n}/response.txt`

**RunLogger is deleted, not deprecated.** Dead code is deleted.

---

## 6. EVENT FLOW

```
run_single() / run_repair_loop() / run_contract_gated() / run_leg_reduction() / retry_harness
    │
    │  (has: case, model, condition, prompt, raw_output, parsed, ev, attempt_index)
    │
    ▼
_emit_event(case, model, condition, prompt, raw_output, parsed, ev, attempt_index, elapsed)
    │
    ├──[1] Build enriched event dict
    │       - Flat metrics (case_id, model, condition, pass, score, ...)
    │       - prompt (full text)
    │       - raw_output (full text)
    │       - evaluation (full ev dict)
    │       - attempt_index
    │       - _schema_version = 2
    │       - observability fields (code_present, failure_source, ...)
    │
    ├──[2] WAL write (MUST succeed first)
    │       live_metrics.emit_event(enriched_event, events_path)
    │       → fsync'd append to events.jsonl
    │
    ├──[3] Redis write (best-effort, metrics only)
    │       redis_metrics.emit_event(run_id, model, trial, case_id, condition, ev, elapsed)
    │       → XADD to Redis stream (no prompt/response)
    │
    └──[4] Human log render (best-effort, full data)
            try:
                log_renderer.render(enriched_event)
            except Exception as e:
                logger.warning("Log render failed for %s/%s: %s", case_id, condition, e)
            → writes prompt.txt, response.txt, evaluation.json, metadata.json
```

**Ordering guarantee:** Step 2 (WAL) completes before step 4 (render). If step 2 fails, step 4 does not execute. If step 4 fails, step 2 has already succeeded. The WAL is always at least as complete as the human logs.

**No other emission points exist.** `write_log()` is deleted. `_emit_metrics_event()` is deleted. `RunLogger` is deleted.

---

## 7. FILESYSTEM LAYOUT AND NAMING RULES

### 7.1 Directory structure

```
{run_dir}/
    events.jsonl                          # WAL (enriched, source of truth)
    metadata.json                         # Run-level metadata (unchanged)
    runner_output.txt                     # Stdout capture (unchanged)

    logs/
        {model_name}/
            case_{case_id}/
                attempt_{attempt_index}/
                    prompt.txt            # Full prompt sent to LLM
                    response.txt          # Full raw response from LLM
                    evaluation.json       # Full evaluation result
                    metadata.json         # Event identity + timestamps + status
```

### 7.2 Path computation (pure function)

```python
def compute_path(run_dir: Path, model: str, case_id: str, attempt_index: int) -> Path:
    safe_model = _sanitize(model)
    safe_case = _sanitize(case_id)
    return run_dir / "logs" / safe_model / f"case_{safe_case}" / f"attempt_{attempt_index}"
```

### 7.3 Sanitization rules

```python
def _sanitize(name: str) -> str:
    """Replace any character that is not alphanumeric, hyphen, underscore, or dot with underscore."""
    return re.sub(r'[^a-zA-Z0-9._-]', '_', name)
```

- Model names like `gpt-4o-mini` → `gpt-4o-mini` (hyphens preserved)
- Case IDs like `alias_config_a` → `alias_config_a` (underscores preserved)
- Pathological inputs like `../../etc/passwd` → `______etc_passwd`
- Empty string → `_empty_`

### 7.4 File contents

**prompt.txt:**
- Raw prompt text, UTF-8
- No JSON wrapping
- No metadata header
- Just the text that was sent to the LLM
- If prompt is missing (schema v1 event): `[prompt not available — event predates schema v2]`
- If prompt is empty string (e.g., `_fallback_run`): `[empty prompt — fallback path]`

**response.txt:**
- Raw response text, UTF-8
- No JSON wrapping
- Just the text returned by the LLM
- If response is missing (schema v1 event): `[response not available — event predates schema v2]`

**evaluation.json:**
- Pretty-printed JSON (indent=2)
- Contains the full `ev` dict as returned by `evaluate_output()`
- Plus: `pass`, `score`, `reasoning_correct`, `code_correct`, `alignment`, `failure_type`
- Plus: execution details (`status`, `passed_tests`, `total_tests`, `error_message`)
- If full evaluation is missing (schema v1): write the subset of flat fields available (`pass`, `score`, etc.)

**metadata.json:**
- Pretty-printed JSON (indent=2)
- Fields:
  ```json
  {
    "run_id": "1c4c10ca",
    "model": "gpt-4o-mini",
    "case_id": "alias_config_a",
    "condition": "baseline",
    "attempt_index": 0,
    "trial": 1,
    "timestamp": "2026-03-26T06:56:55.647351",
    "elapsed_seconds": 6.66,
    "num_attempts": 1,
    "pass": true,
    "score": 1.0,
    "failure_source": "SUCCESS",
    "case_validity": "valid",
    "code_present": true,
    "response_format": "file_dict",
    "parse_tier": 0,
    "_schema_version": 2,
    "_event_identity": "1c4c10ca:alias_config_a:baseline:0"
  }
  ```

---

## 8. IDEMPOTENCY POLICY

### 8.1 Event identity key

```
event_identity = f"{run_id}:{case_id}:{condition}:{attempt_index}"
```

This uniquely identifies a single evaluation attempt. Two events with the same identity are the "same event."

### 8.2 Same event, identical content

**Policy: overwrite.** The four files are written unconditionally. Since the content is identical, the result is identical. No comparison needed. No skip logic. Just write.

Rationale: comparing file contents to detect "already written" adds complexity and I/O (read-before-write) for zero benefit. Overwriting identical content is a no-op at the filesystem level.

### 8.3 Same event, conflicting content

**Policy: overwrite with warning.** If an event with the same identity is replayed with different content (e.g., different evaluation result), the new content overwrites the old. A warning is logged:

```
WARNING: Event 1c4c10ca:alias_config_a:baseline:0 replayed with different content. Overwriting.
```

Rationale: the WAL is append-only. If the same identity appears twice in `events.jsonl` with different content, the second entry wins (last-writer-wins). The human logs should match. The warning alerts the operator to investigate the duplicate in the WAL.

### 8.4 Duplicate event in WAL

The LogRenderer does not deduplicate the WAL. It processes events as they arrive. If `_emit_event()` is called twice for the same identity (which should not happen in correct code), it writes to the WAL twice and renders twice. The human logs end up reflecting the last write. The WAL contains both entries — this is the operator's problem to investigate, not the renderer's problem to fix.

### 8.5 Replay from WAL (offline re-render)

A standalone script can re-render human logs from an existing `events.jsonl`:

```python
def replay_wal(run_dir: Path) -> None:
    events = live_metrics.read_events_safe(run_dir / "events.jsonl")
    renderer = LogRenderer(run_dir)
    for event in events:
        renderer.render(event)
```

This produces identical output to the original run because:
- Path computation is deterministic (pure function of event fields)
- File contents are deterministic (pure function of event fields)
- Overwrite policy means order doesn't matter for identical events
- Last-writer-wins for conflicting events matches WAL ordering

---

## 9. FAILURE MODES AND SAFEGUARDS

### FM-1: Missing fields in event

**Detection:** `LogRenderer.render()` checks for required identity fields (`run_id`, `model`, `case_id`, `condition`, `attempt_index`). Missing identity field → cannot compute path.

**Behavior:** Log `ERROR: Cannot render log — missing identity field '{field}' in event for case_id={case_id}`. Skip rendering. Do not crash. The WAL write already succeeded.

**Recoverable:** Yes — fix the emission code, replay the WAL.

**Surfacing:** ERROR-level log message.

### FM-2: Prompt missing but response present

**Detection:** `event.get("prompt")` is None but `event.get("raw_output")` is not None.

**Behavior:** Write `prompt.txt` with placeholder: `[prompt not available]`. Write `response.txt` normally. Log `WARNING: Event {identity} has response but no prompt.`

**Recoverable:** Only by re-running the evaluation (prompts are not recoverable from response alone).

**Surfacing:** WARNING-level log + placeholder file content.

### FM-3: Response missing but evaluation present

**Detection:** `event.get("raw_output")` is None but `event.get("pass")` is not None.

**Behavior:** Write `response.txt` with placeholder. Write `evaluation.json` normally. Log WARNING.

**Recoverable:** Same as FM-2.

**Surfacing:** WARNING-level log + placeholder file content.

### FM-4: Duplicate event replay

**Detection:** Not explicitly detected — overwrite policy handles it silently.

**Behavior:** Files are overwritten with identical content. No-op in practice.

**Recoverable:** N/A — no corruption.

**Surfacing:** None needed for identical replays. For conflicting replays, WARNING logged (see section 8.3).

### FM-5: Partial human log directory from interrupted write

**Detection:** Directory exists but not all four files are present.

**Behavior:** `render()` writes all four files unconditionally. If only 2 of 4 were written before crash, the next render (or replay) writes all 4 again. The partial state is overwritten.

**Recoverable:** Yes — replay from WAL fills in missing files.

**Surfacing:** No special detection needed. Replay is self-healing.

### FM-6: WAL write succeeded but log rendering failed

**Detection:** `render()` raises an exception, caught by `_emit_event()`.

**Behavior:** `_emit_event()` catches the exception, logs WARNING, continues execution. The WAL is complete. Human logs are incomplete.

**Recoverable:** Yes — replay from WAL regenerates human logs.

**Surfacing:** WARNING-level log: `Log render failed for {case_id}/{condition}: {error}`.

### FM-7: Log rendering succeeded but WAL write failed

**This cannot happen** by construction. WAL write (step 2) executes before log rendering (step 4). If step 2 raises, step 4 never executes. The exception from `live_metrics.emit_event()` propagates up to the caller (hard crash), which is the correct behavior — a WAL write failure is a data integrity failure.

### FM-8: Invalid model / case_id characters in file path

**Detection:** `_sanitize()` applied to all path components.

**Behavior:** Invalid characters replaced with underscore. Deterministic — same input always produces same sanitized output.

**Recoverable:** N/A — no corruption. The mapping is lossy (multiple inputs can map to the same sanitized output) but this is acceptable because `(model, case_id)` pairs are controlled by the benchmark case set, not arbitrary user input.

**Surfacing:** If sanitization changes any character, log DEBUG: `Sanitized path component: '{original}' → '{sanitized}'`.

### FM-9: Very large prompt / response payloads

**Detection:** No detection needed — files are written in a single `open/write/close` cycle.

**Behavior:** Write the full content regardless of size. Prompts are typically 4-8KB, responses 2-12KB. The largest observed response was ~12KB. Even 1MB would write fine.

**Recoverable:** N/A.

**Surfacing:** None needed. If we wanted a guard: log WARNING if payload exceeds 100KB, but still write it.

### FM-10: Existing old runs that do not contain enough data to fully render logs

**Detection:** Check `_schema_version` field. Missing or `1` = old schema.

**Behavior:** Render what's available. Write placeholders for missing fields (see FM-2, FM-3). `evaluation.json` contains only the flat fields present in the event. `prompt.txt` and `response.txt` contain placeholders.

**Recoverable:** No — the data was never captured. The placeholder makes this visible.

**Surfacing:** Each placeholder file's content explicitly states why it's incomplete.

---

## 10. TEST PLAN

### T-1: Logs created for every case and attempt

**Setup:** Run a mock evaluation with 3 cases × 2 conditions. Each emits one event through `_emit_event()`.

**Action:** Check filesystem after all events emitted.

**Assertion:**
- `logs/{model}/case_{case_id}/attempt_0/` exists for all 6 combinations
- Each directory contains exactly 4 files: `prompt.txt`, `response.txt`, `evaluation.json`, `metadata.json`
- `prompt.txt` contains the mock prompt text
- `response.txt` contains the mock response text
- `evaluation.json` is valid JSON with `pass` field
- `metadata.json` is valid JSON with `case_id`, `model`, `condition`, `attempt_index` fields

### T-2: Restart / replay preserves consistent logs

**Setup:** Create `events.jsonl` with 6 events (3 cases × 2 conditions). Run `replay_wal()` to generate logs.

**Action:** Run `replay_wal()` again on the same WAL.

**Assertion:**
- All files are byte-identical before and after second replay
- No extra files or directories created
- File modification times updated but content unchanged

### T-3: Duplicate event causes no duplicate artifacts

**Setup:** Emit the same event (identical content, identical identity) twice via `_emit_event()`.

**Action:** Check filesystem.

**Assertion:**
- Only one directory exists: `attempt_0/`
- Files contain the event content (not doubled/appended)
- `events.jsonl` has 2 lines (the WAL is append-only — duplicates are the WAL's problem)
- Human logs reflect the content of the event (last write wins, but they're identical)

### T-4: Missing required fields fails loudly

**Setup:** Create an event dict missing `case_id`.

**Action:** Call `LogRenderer.render(event)`.

**Assertion:**
- Raises or logs ERROR (depending on whether render is called directly or via `_emit_event()`)
- No files are created in `logs/` for this event
- No crash in the caller if called via `_emit_event()` (caught and warned)

### T-5: Directory structure exactly matches spec

**Setup:** Emit events for model `gpt-4o-mini`, case `alias_config_a`, condition `baseline`, attempt 0.

**Action:** Verify exact path.

**Assertion:**
- Path is `{run_dir}/logs/gpt-4o-mini/case_alias_config_a/attempt_0/`
- Not `{run_dir}/logs/gpt-4o-mini/alias_config_a/attempt_0/` (missing `case_` prefix)
- Not `{run_dir}/logs/gpt-4o-mini/case_alias_config_a/0/` (missing `attempt_` prefix)

### T-6: Replayed identical event is idempotent

**Setup:** Create a renderer. Render an event. Read all 4 files. Render the same event again. Read all 4 files.

**Action:** Compare file contents before and after.

**Assertion:** All 4 files are byte-identical.

### T-7: Replayed conflicting event is handled explicitly

**Setup:** Render event A with `pass=True`. Render event B with same identity but `pass=False`.

**Action:** Check filesystem and logs.

**Assertion:**
- `evaluation.json` contains `"pass": false` (last writer wins)
- A WARNING was logged about conflicting content
- `metadata.json` reflects event B's data

### T-8: Invalid file path characters are sanitized deterministically

**Setup:** Render events with model name `gpt-4o/mini`, case_id `../etc/passwd`.

**Action:** Check filesystem.

**Assertion:**
- Path is `{run_dir}/logs/gpt-4o_mini/case____etc_passwd/attempt_0/`
- No directory traversal occurred
- Same inputs always produce same sanitized paths

### T-9: Large prompt/response payloads render correctly

**Setup:** Create event with 500KB prompt and 500KB response.

**Action:** Render.

**Assertion:**
- `prompt.txt` is exactly 500KB
- `response.txt` is exactly 500KB
- No truncation
- File content matches input byte-for-byte

### T-10: WAL/log divergence is surfaced loudly

**Setup:** Render an event where `render()` is monkeypatched to raise `OSError` on `prompt.txt` write.

**Action:** Call `_emit_event()`.

**Assertion:**
- `events.jsonl` contains the event (WAL succeeded)
- WARNING logged: `Log render failed for {case_id}/{condition}: {error}`
- `logs/` directory may be partially created (acceptable — replay will fix)
- Execution continues (no crash)

### T-11: Schema v1 events produce degraded but valid logs

**Setup:** Create event dict with only v1 fields (14 fields, no prompt/response/attempt_index).

**Action:** Render via LogRenderer.

**Assertion:**
- `prompt.txt` contains placeholder text
- `response.txt` contains placeholder text
- `evaluation.json` contains the available fields (`pass`, `score`, etc.)
- `metadata.json` contains available identity fields, `_schema_version: 1`
- `attempt_index` defaults to 0

### T-12: Structural enforcement — no logging outside `_emit_event()`

**Setup:** Inspect source code of all run_* functions and retry_harness.

**Action:** Search for direct calls to `write_log`, `RunLogger`, `open(` with log paths, or `_emit_metrics_event`.

**Assertion:**
- Zero calls to `write_log()` (function deleted)
- Zero calls to `_emit_metrics_event()` (function deleted)
- Zero references to `RunLogger` (class deleted)
- All logging goes through `_emit_event()` only

---

## 11. IMPLEMENTATION PHASES

### Phase 0: Architecture audit / schema audit

**Already done** (this document, section 2 and section 4).

**Deliverable:** This plan, reviewed and approved.

### Phase 1: Schema repair

**Goal:** Enrich the WAL event with prompt, response, attempt_index, and full evaluation dict.

**Changes:**
1. Add `prompt: str` and `raw_output: str` parameters to `_emit_metrics_event()` (temporary — this function will be replaced in Phase 3, but we do the schema work first).
2. Add `attempt_index: int` parameter.
3. Add `evaluation: dict` field containing the full `ev` dict.
4. Add `_schema_version: 2` to every emitted event.
5. Update all 7 call sites to pass `prompt` and `raw_output`.
6. Update `live_metrics.emit_event()` to accept larger payloads (no schema validation change needed — it already writes whatever dict it receives).

**Verification:** Run one case, inspect `events.jsonl`, confirm prompt/response/evaluation are present.

**Risk:** WAL files become ~100x larger. Mitigate by confirming dashboard aggregation still works (it reads all fields but only uses metrics fields).

### Phase 2: LogRenderer introduction

**Goal:** Create `log_renderer.py` with the `LogRenderer` class.

**Changes:**
1. Create `log_renderer.py` with `LogRenderer` class.
2. Implement `render(event)` — path computation, directory creation, four file writes.
3. Implement `_sanitize()` path component sanitizer.
4. Implement `compute_path()` static method.
5. Implement placeholder handling for missing fields (schema v1 compat).

**Verification:** Unit tests T-1, T-5, T-6, T-8, T-9, T-11 pass.

**No integration yet** — the renderer exists but is not called from the pipeline.

### Phase 3: Integration into `_emit_event()`

**Goal:** Unify `_emit_metrics_event()` and `write_log()` into a single `_emit_event()` function. Wire LogRenderer into the pipeline.

**Changes:**
1. Create `_emit_event()` in `execution.py` with the signature from section 5.1.
2. Move WAL write logic from `_emit_metrics_event()` into `_emit_event()`.
3. Move Redis write logic from `_emit_metrics_event()` into `_emit_event()`.
4. Add `LogRenderer.render()` call after WAL write, wrapped in try/except.
5. Update all 7 call sites: replace paired `write_log()` + `_emit_metrics_event()` calls with single `_emit_event()` call.
6. Delete `_emit_metrics_event()`.
7. Delete `write_log()`.
8. Delete `RunLogger` class and all references.
9. Delete creation of `run.jsonl`, `run_prompts.jsonl`, `run_responses.jsonl` (these files are no longer produced).

**Verification:** Tests T-1 through T-12 pass. Run a 2-case mock evaluation end-to-end, inspect filesystem.

**Risk:** This is the highest-risk phase. Seven call sites change simultaneously. The old write paths are deleted. If any call site is missed, it will fail loudly (deleted function) rather than silently (which is correct — we want crashes on missed call sites, not silent data loss).

### Phase 4: Replay / idempotency validation

**Goal:** Implement and validate WAL replay.

**Changes:**
1. Add `replay_wal(run_dir)` standalone function (in `log_renderer.py` or a script).
2. Run replay on an existing stable run (`stable_gpt-4o-mini_t1_1c4c10ca`).
3. Verify: for schema v1 events, prompt/response get placeholder files. For schema v2 events (if we re-run a model), full files are rendered.

**Verification:** Tests T-2, T-3, T-7 pass. Manual inspection of replayed logs.

### Phase 5: Tests and verification

**Goal:** Full test suite and cleanup.

**Changes:**
1. Create `tests/test_log_renderer.py` with tests T-1 through T-12.
2. Update `tests/test_canonical_pipeline.py` to enforce: no `write_log` calls, no `RunLogger` references, no `_emit_metrics_event` calls in run functions (test T-12).
3. Remove `run_prompts.jsonl` and `run_responses.jsonl` from any code that references them (e.g., `RunLogger` setup code).
4. Verify existing tests still pass (some may reference `RunLogger` or `write_log` — update or delete those).
5. Run a real 2-case ablation and manually inspect the human log directory.

---

## 12. OPEN RISKS / DECISIONS REQUIRING EXPLICIT SIGN-OFF

### R-1: WAL size increase

Adding prompt/response to `events.jsonl` increases file size from ~80KB to ~1-2MB per run. This affects:
- Dashboard aggregation speed (reads full file every 30s)
- Disk usage for multi-trial multi-model ablations

**Options:**
- (A) Accept the increase. Dashboard can skip large fields during read.
- (B) Store prompt/response in a separate WAL sidecar file (`events_content.jsonl`) and keep `events.jsonl` lean. This adds complexity (two files to keep in sync) but preserves dashboard performance.

**Recommendation:** Option A. 1-2MB is trivial. Dashboard can be modified to skip `prompt`/`raw_output` fields if needed (a one-line `del event["prompt"]` during aggregation).

**Decision needed:** Confirm option A or mandate option B.

### R-2: `call_model()` returns response only, not decorated prompt

The `full_prompt` (base prompt + JSON output instruction) is constructed inside `call_model()` and never returned. The human logs will contain the **base prompt** (what the caller passes to `call_model()`), not the **full prompt** (base + output instruction). The output instruction is a constant suffix that can be inferred from the condition.

**Options:**
- (A) Log the base prompt as-is. The output instruction is derivable.
- (B) Modify `call_model()` to return `(response, full_prompt)` tuple. This changes the return type and requires updating every caller.
- (C) Have `_emit_event()` reconstruct the full prompt by appending the output instruction. This duplicates logic.

**Recommendation:** Option A. The base prompt is the interesting part. The JSON output instruction is a fixed suffix that the researcher doesn't need to re-read for every case.

**Decision needed:** Confirm option A, or mandate capturing the full decorated prompt.

### R-3: Retry harness — per-iteration vs. final-only logging

The retry harness runs up to K iterations. Currently, per-iteration data goes to `_write_iteration_log()` (a separate logging function with its own files). Under the new design:

**Options:**
- (A) Emit one event per iteration. Each gets its own `attempt_{k}/` directory. This means K events in the WAL and K directories in human logs per case.
- (B) Emit one event for the final iteration only (current behavior). Intermediate iterations are lost from the human log.
- (C) Emit one event for the final iteration, with the full trajectory (all K prompts/responses) embedded as a list in the event.

**Recommendation:** Option A. One event per iteration. The `attempt_index` field carries the iteration number. This is consistent with the directory structure spec and provides full traceability. The WAL grows by K events per retry case — typically K ≤ 5, so ~5 extra events per retry case.

**Decision needed:** Confirm option A, or mandate a different strategy.

### R-4: Deletion of `run.jsonl`, `run_prompts.jsonl`, `run_responses.jsonl`

These files currently hold the detailed execution log. Under the new design, their content is split between:
- `events.jsonl` (enriched WAL with full prompt/response/evaluation)
- `logs/` directory (human-readable files)

The `run.jsonl` record contains nested `audit` fields (31 fields) that are not all present in the current WAL event schema. Some of these fields (`classifier_prompt`, `classifier_raw_output`, `classifier_verdict`) come from the reasoning evaluator and are observability data, not evaluation results.

**Options:**
- (A) Include all 31 audit fields in the enriched WAL event. This makes the WAL fully self-contained.
- (B) Include only the most important audit fields. Accept that some trace data is only available via replay.
- (C) Keep `run.jsonl` as a secondary log (not a WAL, not a source of truth — just an additional projection). This violates the "single emission point" requirement.

**Recommendation:** Option A. Include all audit fields in the WAL event. The size increase is modest (the fields are mostly short strings). The WAL becomes the complete record. No secondary files needed.

**Decision needed:** Confirm option A or specify which audit fields to include/exclude.

### R-5: Contract-gated path has multiple model calls

`run_contract_gated()` makes 2-3 `call_model()` calls. Under the current design, only the final code generation prompt/response is logged. The contract elicitation prompt/response is lost.

**Options:**
- (A) Emit one event per `call_model()` call. Contract elicitation gets `attempt_0`, code generation gets `attempt_1`, optional retry gets `attempt_2`. The `condition` field distinguishes these (or add a `step` field).
- (B) Emit one event for the final result. Include contract prompt/response as nested fields.
- (C) Accept the loss. Contract elicitation is an intermediate step, not an evaluation.

**Recommendation:** Option B for now. Embed `contract_prompt` and `contract_response` as optional fields in the event. The human log renderer writes them to additional files (`contract_prompt.txt`, `contract_response.txt`) if present. This avoids inflating the attempt count with non-evaluation steps.

**Decision needed:** Confirm option B or choose differently.

---

*End of plan. Awaiting review before any implementation.*
