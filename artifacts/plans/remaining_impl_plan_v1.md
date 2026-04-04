# Remaining Orchestrator v8 Implementation — Plan v1

## Scope

Implement Phases 2d (continued), 2f, and partial Phase 3 from the orchestrator v8 spec. Phase 4 (test suite) deferred to a separate session.

---

## Phase 2d (continued): RunLogger Identity Fields + Worker Lifecycle Events

### Goal
Every event emitted by a worker carries `work_id`, `instance_id`, `attempt`, `sequence`, and string-format `event_id` for dedup. Worker emits `worker.start` and `worker.end` lifecycle events.

### Changes

#### File: `logging_core.py`

1. **RunLogger.__init__**: Accept new optional params `work_id`, `instance_id`, `attempt`. Store as instance fields. Initialize `_sequence = 0`.

2. **RunLogger._base_fields()**: New method returning dict with `work_id`, `instance_id`, `model`, `condition`, `trial`, `attempt`, `sequence` (current). Called by `_write_event`, `log_structured_error`, `emit_event`.

3. **BaseLogger._write_event()**: Change `event_id` from integer (`self._event_counter`) to string format. When `instance_id` is set: increment `_sequence`, set `event_id = f"{instance_id}__{sequence:06d}"`. When not set (legacy/orchestrator path): keep integer counter as before for backward compat.

4. **RunLogger.emit_event()**: Inject `work_id`, `instance_id`, `attempt`, `sequence` into the record dict (in the `run` section and at top level).

5. **RunLogger.log_structured_error()**: New method per spec Section 21.3. Emits structured error events via `_write_event`. Tracks `_error_emitted_for: set[str]` and `_primary_error_for: dict[str, str]`.

6. **RunLogger.fail_case()**: Add enforcement — if `case_id not in self._error_emitted_for`, emit `case.error.unclassified` first.

#### File: `runner.py`

7. **run_ablation_mode()**: Read `_work_id`, `_instance_id`, `_attempt` from config (set by orchestrator's `derive_trial_config`). Pass to RunLogger constructor. If not present (standalone mode), default to None (legacy behavior preserved).

8. **run_ablation_mode()**: After `run.start` event, emit `worker.start` event with `pid`, `config_sha256`, `case_ids`.

9. **run_ablation_mode()**: Before `run.end` event, emit `worker.end` event with `completed_cases`, `failed_cases`, `pass_rate`, `elapsed_seconds`.

10. **Heartbeat**: In `run_all()`, write `heartbeat.json` atomically every 30s with `work_id`, `instance_id`, `pid`, `updated_at`, `current_case_id`, `cases_completed`, `sequence`.

---

## Phase 2f: Structured Error Promotion

### Goal
Every error affecting correctness is emitted as a structured `case.error.*` event before `case.failed`. stderr is debug-only.

### Changes

#### File: `runner.py`

11. **_run_one() except block (line 169-174)**: Before `logger.fail_case()`, emit `logger.log_structured_error("case.error.exception", cid, {...})` with `exception_type`, `error`, `traceback_summary`.

#### File: `execution_v2.py`

12. **run_v2() line 104-112**: When parse invariant violated, emit `logger.log_structured_error("case.error.parse", cid, {...})` with `parse_stage="v2_invariant"`, `error` description.

#### File: `exec_eval.py`  

Error promotion in exec_eval.py is handled differently: exec_eval returns structured result dicts (not exceptions). The errors are already captured in the return values (`syntax_error`, `runtime_error`, `assembly_error` fields). These flow back through execution_v2.py/runner.py where they become part of the `raw_ev` dict logged by `end_case()`. No additional structured error events needed in exec_eval.py itself — the error information is already in the canonical event.

The structured error events are for cases where execution FAILS (exception) rather than cases where execution SUCCEEDS but the test doesn't pass.

---

## Phase 3 (partial): Delete Dead Code

### Changes

13. **runner.py**: Delete `COND_DESCRIPTIONS` list (lines 23-32, 0 uses outside tests — verify first).
14. **Verify** `parallel_runner.py` is not imported anywhere except the old dispatch path. If safe, delete is deferred until equivalence gate passes.

---

## Files Touched

| File | Nature of change |
|---|---|
| `logging_core.py` | Add identity fields, sequence counter, string event_id, `_base_fields()`, `log_structured_error()`, `fail_case()` enforcement |
| `runner.py` | Pass identity fields to RunLogger, emit worker.start/end, heartbeat, structured error in exception handler |
| `execution_v2.py` | Emit case.error.parse on invariant violation |

## Invariants

- All existing tests must continue to pass (1611 pass, 150 pre-existing failures)
- Standalone runner mode (no orchestrator) must work unchanged (identity fields default to None, event_id stays integer)
- Orchestrator-spawned workers get string event_ids with sequence
- Every `case.failed` preceded by at least one `case.error.*`
- No new dependencies

## Risks

- `event_id` type change (int → str) could break aggregate.py or other consumers that compare event_ids numerically. Mitigation: only change format when `instance_id` is set; legacy path keeps int.
- `fail_case` enforcement could surface latent paths missing error events. Mitigation: `case.error.unclassified` fallback ensures no crash.
