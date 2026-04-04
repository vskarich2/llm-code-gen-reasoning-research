# Config System Repair Plan V2.2 Revised

Strict patch revision of V2.2. All V2.2 content remains in force except where explicitly superseded below. This revision addresses five remaining structural weaknesses identified in the V2.2 review.

---

## Changes from V2.2

| Fix | V2.2 Defect | V2.2-R Correction |
|---|---|---|
| R1 | Generation output contract checked only via template/compiler, not at runtime after parsing | Explicit runtime assertion in `_reconstruct_and_execute()` after parsing, before any downstream consumption |
| R2 | Prompt file naming predicts future event_id via `logger._event_counter + 1` | Logger-allocated `prompt_id` via `logger.next_prompt_id()` — stable, already-assigned, no prediction |
| R3 | `REQUIRED_EVENT_FIELDS` and `CONFIG_LOG_COVERAGE` are two manually maintained lists that can drift | `REQUIRED_EVENT_FIELDS` deleted; derived programmatically from `CONFIG_LOG_COVERAGE` at runtime |
| R4 | Multi-call indexing has no single owner — callers pass arbitrary `call_index` values | Logger owns call index via `logger.next_call_slot()` — monotonic, auto-incrementing, reset per prompt_id |
| R5 | No storage/retention policy for full prompt logging | Explicit policy: raw files retained indefinitely within run directory; optional post-run archival compresses completed runs; smoke outputs under `_smoke/` |
| R6 | `next_prompt_id()` called inside `call_model()` breaks multi-call grouping | `call_model()` does NOT allocate prompt_id; caller allocates once per logical unit and passes it |
| R7 | Generation contract violation uses wrong execution_category, contaminates metrics | Use `STRUCTURAL_FAILURE` category with `failure_type=GENERATION_CONTRACT_VIOLATION`; classifier and evaluator do not run |
| R8 | `_required_event_fields_from_coverage()` does not filter by event type | Validation restricted to `execution_eval` events only; `run_start.*` paths excluded from runtime check |
| R9 | Prompt directory creation does not surface errors | Directory creation failures raise, not silently ignored; idempotent via `exist_ok=True` |

---

## FIX R1 — Generation Output Contract Runtime Enforcement (supplements V2.2 Fix 2)

### Problem

V2.2 defines `GENERATION_OUTPUT_CONTRACT` and validates it at the smoke gate and in `_classify_reasoning()`. But there is no assertion between parsing success and the first downstream consumer (reconstruction). A field rename like `fix_strategy → fix_plan` can produce a parsed output that passes the parser (parser is field-agnostic) but silently produces a None `fix_strategy` in the artifact, which then flows through reconstruction and into the classifier as garbage.

### Correction

Add an explicit contract assertion in `execution_v2.py:_reconstruct_and_execute()` — the single point where parsed generation output transitions to downstream consumption.

File: `core/pipeline/orchestration/execution_v2.py`

Insert at the top of `_reconstruct_and_execute()`, after the `parsed_gen` argument is received but before any consumption:

```python
def _reconstruct_and_execute(parsed_gen, case, config, logger):
    # ── Generation output contract assertion ──
    if parsed_gen.parse_valid and parsed_gen.full_json:
        fj = parsed_gen.full_json
        missing = GENERATION_OUTPUT_CONTRACT - set(fj.keys())
        if missing:
            cid = case["id"]
            _log.error(
                "GENERATION CONTRACT VIOLATION: case=%s missing fields=%s "
                "observed=%s. Marking as structural pipeline failure.",
                cid, sorted(missing), sorted(fj.keys()),
            )
            from core.pipeline.reconstructor import ReconstructionResult
            recon = ReconstructionResult(
                status="GENERATION_CONTRACT_VIOLATION",
                files={},
            )
            from core.pipeline.execution.exec_canonical import _make_result
            exec_result = _make_result(
                case,
                {"error_type": "GenerationContractViolation",
                 "error_message": f"Missing required fields: {sorted(missing)}",
                 "failure_reasons": [
                     f"Generation output missing: {sorted(missing)}. "
                     f"Observed: {sorted(fj.keys())}."
                 ]},
                "STRUCTURAL_FAILURE", 0.0, ran=False,
            )
            exec_result["failure_type"] = "GENERATION_CONTRACT_VIOLATION"
            return recon, "", exec_result
    
    # ... rest of existing function unchanged
```

### Taxonomy update

`STRUCTURAL_FAILURE` must be added to `exec_canonical.py:ALL_CATEGORIES`:

```python
ALL_CATEGORIES = frozenset({
    ...,
    "STRUCTURAL_FAILURE",  # NEW: generation/pipeline contract violation
})
```

### Why this location

`_reconstruct_and_execute()` is the single gateway between parser output and all downstream stages (reconstruction, execution, classification, evaluation). Every code path that consumes parsed generation output passes through here — both `run_v2()` and `run_retry_v2()` call it.

### Failure behavior

- Missing field: logged as `GENERATION CONTRACT VIOLATION` with case_id and observed fields
- Event marked with `execution_category = "STRUCTURAL_FAILURE"` — this is a pipeline infrastructure failure, not a model-quality failure
- `failure_type = "GENERATION_CONTRACT_VIOLATION"` for downstream analysis filtering
- Classifier does NOT run (parse_status is not "success" when contract fails, so `_classify_reasoning()` skips it)
- Evaluator: `_compute_evaluation()` receives `S=False` (recon.status != "SUCCESS"), producing `outcome_class = "serialization_failure"` — this is correct and excludes the case from LEG/pass-rate metrics
- No contamination of model-quality metrics: the case is classified as a pipeline failure, not a model failure

### What is NOT changed

The existing contract assertions remain:
- `_validate_pipeline_contracts()` at smoke gate (static contract consistency)
- Runtime assertion in `_classify_reasoning()` (classifier output contract)

R1 adds the missing third assertion: generation output contract at the parsing→reconstruction boundary.

---

## FIX R2 — Logger-Allocated Prompt ID (supersedes V2.2 Fix 4 prompt naming)

### Problem

V2.2 uses `event_id = logger._event_counter + 1` to predict the next event ID for the prompt filename. This is fragile: any intermediate logging, refactoring, or reordering breaks the prediction.

### Correction: Dedicated prompt_id allocator

Add to `RunLogger` in `core/logging_/logging_core.py`:

```python
class RunLogger(BaseLogger):
    def __init__(self, ...):
        # ... existing init ...
        self._prompt_counter = 0
        self._current_call_slot = 0
    
    def next_prompt_id(self) -> int:
        """Allocate a unique prompt identifier. Monotonic per worker.
        
        This is NOT the event_id. It is a dedicated sequence for prompt files.
        Resets _current_call_slot to 0 for this new prompt group.
        
        CALLER RESPONSIBILITY: call this ONCE per logical unit (event / retry
        iteration), then reuse the returned id across all call_model() calls
        within that unit. call_model() does NOT allocate prompt_id.
        """
        self._prompt_counter += 1
        self._current_call_slot = 0
        assert self._current_call_slot == 0, "call_slot reset failed"
        return self._prompt_counter
    
    def next_call_slot(self) -> int:
        """Allocate the next call slot within the current prompt group.
        
        Returns the current slot index and advances it.
        Used for multi-call events (generation + critique + classifier).
        Must be called after next_prompt_id() has been called at least once.
        """
        assert self._prompt_counter > 0, (
            "next_call_slot() called before next_prompt_id(). "
            "Caller must allocate a prompt_id first."
        )
        slot = self._current_call_slot
        self._current_call_slot += 1
        return slot
```

### Prompt file naming

File: `core/logging_/prompt_store.py`

```python
def write_prompt(run_dir: Path, prompt_id: int, call_slot: int,
                 prompt: str) -> str:
    """Write prompt to plain text file. Returns relative path from run_dir.
    
    prompt_id: allocated by logger.next_prompt_id()
    call_slot: allocated by logger.next_call_slot()
    """
    prompt_dir = run_dir / "prompts"
    try:
        prompt_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"Failed to create prompt directory {prompt_dir}: {e}. "
            f"Run directory may be unwritable."
        ) from e
    
    filename = f"p{prompt_id:06d}_call{call_slot}.txt"
    path = prompt_dir / filename
    
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, prompt.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    
    return f"prompts/{filename}"
```

### Integration: caller allocates prompt_id, NOT call_model()

**Critical rule:** `call_model()` does NOT allocate `prompt_id`. The caller allocates it once per logical unit (event / retry iteration) and passes it to every `call_model()` invocation within that unit.

**In `call_model()` signature:**

```python
def call_model(
    prompt: str, model: str, ...,
    prompt_id: int = 0,
    call_slot: int = 0,
    truncated: bool = False,
    truncation_reason: str | None = None,
) -> ModelCallResult:
```

`call_model()` receives `prompt_id` and `call_slot` as parameters. It writes the prompt file and attaches `prompt_meta`. It does NOT call `next_prompt_id()` or `next_call_slot()`.

**In `execution_v2.py:run_v2()` (baseline path):**

```python
prompt_id = logger.next_prompt_id()

# Generation call
gen_slot = logger.next_call_slot()  # returns 0
gen_result = call_model(prompt, model=model, ...,
                        prompt_id=prompt_id, call_slot=gen_slot)

# ... later, classification call (same prompt_id, different slot)
cls_slot = logger.next_call_slot()  # returns 1
cls_result = call_model(cls_prompt, model=eval_model, ...,
                        prompt_id=prompt_id, call_slot=cls_slot)
```

**In `retry_v2.py:run_retry_v2()` (retry path):**

```python
for k in range(max_iterations):
    prompt_id = logger.next_prompt_id()  # new group per iteration
    
    # Generation
    gen_slot = logger.next_call_slot()  # 0
    gen_result = call_model(prompt, ..., prompt_id=prompt_id, call_slot=gen_slot)
    
    # Critique (if applicable)
    crit_slot = logger.next_call_slot()  # 1
    crit_result = call_model(crit_prompt, ..., prompt_id=prompt_id, call_slot=crit_slot)
    
    # Classifier hint (if applicable)
    cls_slot = logger.next_call_slot()  # 2
    cls_result = call_model(cls_prompt, ..., prompt_id=prompt_id, call_slot=cls_slot)
```

This produces:
- Iteration 0: `p000001_call0.txt`, `p000001_call1.txt`, `p000001_call2.txt`
- Iteration 1: `p000002_call0.txt`, `p000002_call1.txt`, `p000002_call2.txt`

Grouping is preserved. All calls within one logical unit share the same `prompt_id`.

**In `call_model()` body (llm.py):**

```python
prompt_hash = hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()
prompt_length = len(full_prompt)

prompt_file = None
if logger is not None:
    prompt_file = write_prompt(
        run_dir=logger._run_dir,
        prompt_id=prompt_id,
        call_slot=call_slot,
        prompt=full_prompt,
    )

# Attach to call record
prompt_meta = {
    "prompt_id": prompt_id,
    "call_slot": call_slot,
    "prompt_hash": prompt_hash,
    "prompt_length": prompt_length,
    "prompt_file": prompt_file,
    "truncated": truncated,
    "truncation_reason": truncation_reason,
}
```

### Traceability

The event's `event_id` (from `emit_event()`) and the prompt's `prompt_id` are linked via the `prompt_meta` dict inside the event record. They are independent sequences — no prediction needed. All calls within a logical unit share the same `prompt_id` but have distinct `call_slot` values.

### What is deleted

- `logger._event_counter + 1` prediction pattern
- `event_id` parameter in `write_prompt()` signature
- Any `next_prompt_id()` or `next_call_slot()` calls inside `call_model()`

### Filename format change

Before: `e{event_id:06d}_call{call_index}.txt`
After: `p{prompt_id:06d}_call{call_slot}.txt`

The `p` prefix distinguishes prompt files from event references. The prompt_id is stable and assigned before the file is written.

---

## FIX R3 — Derived Required Event Fields (supersedes V2.2 Fix 7 partial)

### Problem

V2.2 maintains two separate registries: `CONFIG_LOG_COVERAGE` (declared coverage) and `REQUIRED_EVENT_FIELDS` (runtime validation list). These can drift independently.

### Correction

Delete the manually maintained `REQUIRED_EVENT_FIELDS` list. Derive the runtime validation set programmatically from `CONFIG_LOG_COVERAGE`.

File: `core/config/experiment_config.py`

```python
def _required_event_fields_from_coverage(
    event_type: str = "execution_eval",
) -> list[str]:
    """Derive runtime-required event field paths from CONFIG_LOG_COVERAGE.
    
    Filters:
    - Excludes NON_OBSERVABLE entries
    - Excludes run_start.* entries (those are in pipeline_state events, not execution_eval)
    - Only returns paths relevant to the specified event_type
    
    The returned paths are dotted event-dict paths used by
    _validate_event_log_coverage() for runtime checking.
    """
    # Prefix → event type mapping
    _PREFIX_TO_EVENT_TYPE = {
        "run_start.": "pipeline_state",
        "ev.": "execution_eval",
    }
    
    required = []
    for config_path, log_path in CONFIG_LOG_COVERAGE.items():
        if log_path.startswith("NON_OBSERVABLE:"):
            continue
        
        # Determine which event type this log path belongs to
        path_event_type = None
        resolved_path = log_path
        for prefix, etype in _PREFIX_TO_EVENT_TYPE.items():
            if log_path.startswith(prefix):
                path_event_type = etype
                resolved_path = log_path[len(prefix):]
                break
        
        if path_event_type is None:
            # No prefix match — assume execution_eval
            path_event_type = "execution_eval"
            resolved_path = log_path
        
        if path_event_type != event_type:
            continue
        
        required.append(resolved_path)
    return required
```

### Updated validation function

File: `core/pipeline/orchestration/execution_v2.py`

```python
def _validate_event_log_coverage(ev: dict, event_type: str = "execution_eval") -> list[str]:
    """Check that required log fields are present in an emitted event.
    
    Required fields are derived from CONFIG_LOG_COVERAGE, filtered to
    the specified event_type. Only validates fields that belong to this
    event type — run_start fields are not checked on execution_eval events.
    
    Returns list of missing field paths (empty = all present).
    """
    from core.config.experiment_config import _required_event_fields_from_coverage
    
    required = _required_event_fields_from_coverage(event_type)
    missing = []
    for dotted_path in required:
        parts = dotted_path.split(".")
        node = ev
        found = True
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                found = False
                break
        if not found:
            missing.append(dotted_path)
    return missing
```

### What is deleted

- The manually maintained `REQUIRED_EVENT_FIELDS` list (V2.2 lines 659-672)

### Benefit

Adding a new observable config field to `CONFIG_LOG_COVERAGE` automatically updates runtime validation. One list to maintain, not two.

### Audit script integration

The audit script check (V2.2 validation matrix #48) changes from "every CONFIG_LOG_COVERAGE entry not marked NON_OBSERVABLE has a corresponding REQUIRED_EVENT_FIELDS entry" to "verify `_required_event_fields_from_coverage()` returns a non-empty list that covers all observable entries." This is a simpler check because the derivation is programmatic.

---

## FIX R4 — Single-Owner Multi-Call Indexing (supplements V2.2 Fix 4)

### Problem

V2.2 says "call_index is tracked by the caller" and lists generation=0, critique=1, classifier_hint=2. This is caller-managed, fragile, and produces collisions if callers get the ordering wrong.

### Correction: Logger owns call slot advancement

The logger is the sole owner of call slot state. Callers request a slot, they do not assign one.

### State model

```
prompt_id:  monotonic per worker, allocated by logger.next_prompt_id()
call_slot:  monotonic within a prompt_id, allocated by logger.next_call_slot()
```

### Lifecycle

1. Before the first LLM call for a case/event, the caller calls `logger.next_prompt_id()` → resets call_slot to 0, returns prompt_id
2. Before each LLM call within that group, the caller calls `logger.next_call_slot()` → returns current slot, advances counter
3. The returned slot is passed to `write_prompt()` and embedded in `prompt_meta`

### Example: retry iteration with generation + critique + classifier hint

```python
# In run_retry_v2(), at the start of each iteration:
prompt_id = logger.next_prompt_id()

# Generation call
gen_slot = logger.next_call_slot()  # returns 0
write_prompt(logger._run_dir, prompt_id, gen_slot, gen_prompt)
gen_result = call_model(gen_prompt, ..., prompt_id=prompt_id, call_slot=gen_slot)

# Critique call (if applicable)
crit_slot = logger.next_call_slot()  # returns 1
write_prompt(logger._run_dir, prompt_id, crit_slot, crit_prompt)
crit_result = call_model(crit_prompt, ..., prompt_id=prompt_id, call_slot=crit_slot)

# Classifier hint call (if applicable)
cls_slot = logger.next_call_slot()  # returns 2
write_prompt(logger._run_dir, prompt_id, cls_slot, cls_prompt)
cls_result = call_model(cls_prompt, ..., prompt_id=prompt_id, call_slot=cls_slot)
```

### Collision impossibility

- `prompt_id` is monotonic per worker process (single-threaded within worker)
- `call_slot` is monotonic within a `prompt_id` group
- Filename `p{prompt_id:06d}_call{call_slot}.txt` is unique within a run directory
- `O_CREAT | O_EXCL` in `write_prompt()` fails loudly on collision (defense in depth)
- Workers write to separate run directories — no cross-worker collision possible

### What is deleted

- Caller-managed `call_index` parameter from `call_model()` signature
- All hardcoded `call_index=0`, `call_index=1`, `call_index=2` in callers

### What is added to call_model signature

```python
def call_model(
    prompt: str, model: str, ...,
    prompt_id: int = 0,
    call_slot: int = 0,
    truncated: bool = False,
    truncation_reason: str | None = None,
) -> ModelCallResult:
```

The `prompt_id` and `call_slot` are passed through to `prompt_meta` and to `write_prompt()`. Defaults of 0 are for the case where no logger is present (mock mode). `call_model()` never calls `next_prompt_id()` or `next_call_slot()` — it only consumes the values the caller provides.

---

## FIX R5 — Storage and Retention Policy (new section)

### Artifacts per run

| Directory | Contents | Size estimate per case | Retention |
|---|---|---|---|
| `prompts/` | Plain-text prompt files, one per LLM call | ~20-50 KB per call | Retained indefinitely within run directory |
| `calls/` | Full call records (JSON with prompt+response+metadata) | ~50-200 KB per call | Retained indefinitely within run directory |
| `calls_flat/` | Human-readable call summaries | ~50-200 KB per call | Retained indefinitely within run directory |
| `events.jsonl` | Structured events with references (no inline prompts) | ~2-5 KB per event | Retained indefinitely within run directory |

### Size projections

For a typical ablation (58 cases × 3 models × 5 conditions × 50 trials = 43,500 work items):
- ~2 LLM calls per work item (generation + classification) = 87,000 calls
- Prompt files: 87,000 × 35 KB avg = ~3.0 GB
- Call records: 87,000 × 100 KB avg = ~8.7 GB
- Events: 43,500 × 3 KB avg = ~0.13 GB
- **Total: ~12 GB per full ablation**

### Policy

1. **Raw prompt files are never deleted automatically.** They are lossless records required for reproducibility.

2. **No compression during run.** Raw files are written as plain text during execution. Compression adds latency and complexity to the write path.

3. **Post-run archival (optional).** After a run completes and results are analyzed, the entire run directory may be compressed:
   ```bash
   tar -czf logs/archive/v3_ablation_123.tar.gz logs/runs/v3_ablation_123/
   ```
   This is a manual operator action, not an automated system behavior. The compressed archive retains all raw files.

4. **Smoke outputs under `_smoke/`.** Smoke gate outputs live in `{run_dir}/_smoke/` and obey the same rules. They are small (4-8 cases) and do not warrant special treatment.

5. **No sampling, no pruning, no inline storage.** Prompt logging is always full, always lossless, always in separate files. The events.jsonl references prompt files by relative path — it never contains the raw prompt text.

6. **Disk space monitoring is the operator's responsibility.** The system does not enforce disk quotas. If disk space is a concern, the operator archives completed runs.

### Tooling (optional, post-V2.2)

A future `scripts/archive_run.py` script may:
- Verify run is complete (all work items terminal)
- Compress the entire run directory
- Optionally remove the uncompressed directory after verification
- Never delete prompt files without producing a verifiable archive first

This script is not part of the V2.2 implementation. It is documented as a known future need.

---

## Updated Migration Plan (addendum to V2.2 migration plan)

Insert between V2.2 Steps 9 and 10:

### Step 9.5: Add logger prompt_id/call_slot allocators

File: `core/logging_/logging_core.py`
- Add `_prompt_counter` and `_current_call_slot` to `RunLogger.__init__()`
- Add `next_prompt_id()` and `next_call_slot()` methods
- Update `prompt_store.py:write_prompt()` signature to use `prompt_id` and `call_slot`
- Update `llm.py:call_model()` to accept `prompt_id` and `call_slot`, use logger allocators
- Remove caller-managed `call_index` from all call sites in `execution_v2.py` and `retry_v2.py`

### Step 9.7: Add generation contract assertion

File: `core/pipeline/orchestration/execution_v2.py`
- Add `GENERATION_OUTPUT_CONTRACT` assertion at top of `_reconstruct_and_execute()`

### Step 11 revision: Derive required event fields

File: `core/config/experiment_config.py`
- Add `_required_event_fields_from_coverage()` function
- Delete manual `REQUIRED_EVENT_FIELDS` list

File: `core/pipeline/orchestration/execution_v2.py`
- Update `_validate_event_log_coverage()` to call `_required_event_fields_from_coverage()`

---

## Updated Validation Matrix (addendum to V2.2)

All V2.2 checks retained. New V2.2-R checks:

| # | Check | Pass Criterion |
|---|---|---|
| 49 | Generation contract enforced at runtime | Parse a response missing `fix_strategy`, run through `_reconstruct_and_execute()` → event has `execution_category="STRUCTURAL_FAILURE"` and `failure_type="GENERATION_CONTRACT_VIOLATION"` |
| 50 | Generation contract passes valid output | Parse a response with all three fields → reconstruction proceeds normally |
| 51 | Prompt filename uses logger-allocated prompt_id | `grep -rn "_event_counter + 1" core/` → zero matches |
| 52 | Prompt filename uses logger-allocated call_slot | `grep -rn "call_index" core/pipeline/llm.py core/logging_/prompt_store.py` → zero matches |
| 53 | Multi-call grouping preserved | One retry iteration with generation+critique+classifier produces `p000001_call0.txt`, `p000001_call1.txt`, `p000001_call2.txt` — all share same prompt_id, all distinct |
| 54 | REQUIRED_EVENT_FIELDS is not manually maintained | `grep -n "REQUIRED_EVENT_FIELDS" core/` → only the derivation function, no hardcoded list |
| 55 | Derived required fields match CONFIG_LOG_COVERAGE | `_required_event_fields_from_coverage("execution_eval")` returns non-empty list; every entry is a valid nested dict path in a well-formed execution_eval event |
| 56 | Storage policy documented | `prompts/` directory exists in smoke output; files are plain text; no inline prompt in events.jsonl |
| 57 | Smoke prompt files present | `ls {run_dir}/_smoke/prompts/` returns ≥1 `.txt` file per smoke case |
| 58 | next_prompt_id monotonic | Across 5 consecutive calls, prompt_ids are strictly increasing |
| 59 | next_call_slot resets on new prompt_id | After `next_prompt_id()`, first `next_call_slot()` returns 0; assertion fires if violated |
| 60 | call_model does NOT allocate prompt_id | `grep -n "next_prompt_id\|next_call_slot" core/pipeline/llm.py` → zero matches |
| 61 | STRUCTURAL_FAILURE in taxonomy | `grep "STRUCTURAL_FAILURE" core/pipeline/execution/exec_canonical.py` → present in ALL_CATEGORIES |
| 62 | Generation contract violation excluded from LEG | Case with STRUCTURAL_FAILURE has outcome_class="serialization_failure", not LEG |
| 63 | Event type filter works | `_required_event_fields_from_coverage("execution_eval")` does NOT include `run_start.*` paths |
| 64 | Prompt directory creation failure raises | Pass unwritable path to `write_prompt()` → RuntimeError mentioning "unwritable" |

---

## Updated Closure Table (addendum to V2.2)

| Fix | Issue | Closed By |
|---|---|---|
| R1 | Generation output contract only enforced at compile/smoke, not after parsing | Runtime assertion in `_reconstruct_and_execute()` checks `GENERATION_OUTPUT_CONTRACT` against parsed `full_json`; uses `STRUCTURAL_FAILURE` category (Step 9.7) |
| R2 | Prompt filenames predict future event_id | Logger-allocated `prompt_id` via `next_prompt_id()` — no prediction (Step 9.5) |
| R3 | `REQUIRED_EVENT_FIELDS` and `CONFIG_LOG_COVERAGE` drift independently | `REQUIRED_EVENT_FIELDS` deleted; derived from `CONFIG_LOG_COVERAGE` by `_required_event_fields_from_coverage()` (Step 11 revision) |
| R4 | Multi-call indexing has no single owner | Logger owns `call_slot` via `next_call_slot()` — callers request, not assign (Step 9.5) |
| R5 | No storage/retention policy for prompt logs | Explicit policy: raw files retained indefinitely, optional post-run archival, no inline storage, no sampling (documented in Fix R5) |
| R6 | `next_prompt_id()` called inside `call_model()` breaks multi-call grouping | `call_model()` does NOT allocate prompt_id; caller allocates once per logical unit (Step 9.5) |
| R7 | Generation contract violation uses wrong execution_category, contaminates LEG metrics | `STRUCTURAL_FAILURE` added to taxonomy; `failure_type=GENERATION_CONTRACT_VIOLATION`; classifier/evaluator do not run; outcome_class is `serialization_failure` (Step 9.7) |
| R8 | `_required_event_fields_from_coverage()` mixes event types | Event type filter added; `run_start.*` paths excluded from `execution_eval` validation (Step 11 revision) |
| R9 | Prompt directory creation failure silently ignored | `mkdir` wrapped in try/except that raises RuntimeError on failure (Step 9.5) |
