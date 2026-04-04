# System Repair Plan v1

**Date:** 2026-04-04
**Status:** PLAN — requires approval before implementation
**Scope:** Fix all P0/P1 bugs from system audit

---

## Verified Bug List (code-traced, not assumed)

### P0 — CRITICAL (blocks correct operation)

**P0-1: events.jsonl APPEND mode causes duplicates on retry**
- File: `core/logging_/logging_core.py:255`
- Code: `self._events_file = open(self._events_path, "a", encoding="utf-8")`
- Root cause: Orchestrator relaunches failed worker in same attempt_001 dir. Old events remain. New events appended. Duplicate sequence numbers → validation fails.
- Fix: Truncate events.jsonl if it already exists when logger opens. The file is per-worker-attempt; there is no legitimate reason to append to a prior attempt's events.
- Specifically: change `"a"` to `"w"` in BaseLogger.__init__. Each worker run creates a fresh logger that owns this file exclusively.

**P0-2: Oracle logger not passed in retry_v2.py**
- File: `core/pipeline/orchestration/retry_v2.py:452`
- Code: `oracle_result = run_oracle_evaluation(raw_rc, raw_fs, case, config)`
- Root cause: Missing `logger=logger, case_id=cid, condition=condition, parent_event_id=last_parent_eid`
- Fix: Add the 4 missing parameters.

**P0-3: Oracle inputs silently defaulted to empty string**
- File: `core/pipeline/orchestration/execution_v2.py:140-148`
- Code: `raw_root_cause or ""` hides None → makes SKIPPED indistinguishable from genuine short reasoning
- Fix: Pass None directly. Oracle's `is_unjudgable()` already handles None. Remove the `or ""` and the warning logs. Let oracle_inline handle it with an explicit status:
  - None input → `status: "SKIPPED", error: "missing_root_cause"` (distinct from `error: "pre_filter:reasoning_too_short"`)

### P1 — HIGH (correctness degraded)

**P1-1: oracle.timeout parsed but never used**
- File: `core/evaluation/oracle_inline.py:105-111`
- Config: `config.oracle.timeout` exists (default 30)
- But: `call_model()` has no `timeout` parameter. The timeout is controlled by `anthropic_client_timeout` (120s) at the client level.
- Fix: There is no per-call timeout mechanism in call_model/openai/anthropic wrappers. The oracle.timeout config should be removed or documented as "reserved for future use." Honest fix: remove the field from OracleConfig and default.yaml to avoid confusion.

**P1-2: FINAL_ONLY sampling dead code**
- File: `core/pipeline/orchestration/retry_v2.py:576-585`
- Code references `_parsed_fj` which is never stored in trajectory entries
- Fix: Remove the FINAL_ONLY deferred execution block. Store raw_root_cause and raw_fix_strategy in trajectory entries if FINAL_ONLY is to be supported. For now: remove dead code, log a warning if FINAL_ONLY is configured, and fall back to ALWAYS.

**P1-3: AST checker exceptions at DEBUG level only**
- File: `core/evaluation/ast_eval.py:160-177`
- Fix: Change `_log.debug` to `_log.warning` for checker exceptions.

**P1-4: parent_event_id or 0 ambiguity**
- File: `core/pipeline/llm.py:123`
- Code: `parent_event_id=parent_event_id or 0`
- Fix: `parent_event_id if parent_event_id is not None else 0`

**P1-5: finalize() not in try/finally**
- File: `core/pipeline/orchestration/runner.py:634-709`
- Fix: Wrap logger lifecycle in try/finally.

### Retracted findings

- subprocess_timeout: VERIFIED as wired correctly at exec_canonical.py:300. The function default of 30 is overridden by config. NOT a bug.
- experiment.seed: Parsed but unused. Low priority, not blocking. Leave as-is.

---

## Implementation Order

1. P0-1: Fix events.jsonl write mode
2. P0-2: Fix retry oracle logger
3. P0-3: Fix oracle input handling (None vs empty string)
4. P1-1: Remove oracle.timeout (unused, misleading)
5. P1-2: Remove FINAL_ONLY dead code
6. P1-3: Upgrade AST exception logging
7. P1-4: Fix parent_event_id falsy check
8. P1-5: Wrap finalize in try/finally
9. Add tests for all fixes

---

## Verification

After all fixes:
1. Run config round-trip test
2. Run orchestrator with baseline_v3 + leg_reduction_lean_v3 (the combo that exposed duplicates)
3. Verify 0 duplicate events
4. Verify oracle call events present in retry path
5. Verify all workers SUCCEED
