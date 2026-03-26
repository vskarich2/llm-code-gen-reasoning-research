# Hang Diagnostic Plan

**Date:** 2026-03-26
**Status:** Phase 1 ready for implementation. Phase 2 blocked on Phase 1 results.
**Problem:** Runner hangs at ~108/116 evaluations during ablation runs.

---

## Root Cause Hypothesis

`client.responses.create()` in `llm.py:_openai_call()` stalls on an OpenAI API
response. The SDK default timeout is 600s. A single stalled call blocks the
entire serial process. By eval 108, 216+ API calls have been made — the
probability of hitting at least one stall is non-trivial.

This is a hypothesis. Phase 1 proves or disproves it.

---

## Phase 1 — Instrumentation (no behavior change)

### What changes

One file: `llm.py`. Three additions.

1. Module-level call counter:
```python
import itertools
_call_counter = itertools.count(1)
```

2. Log before API call:
```python
call_n = next(_call_counter)
_llm_log.info("OPENAI_CALL_START call_n=%d model=%s prompt_len=%d", call_n, model, len(prompt))
t0 = _time.monotonic()
```

3. Log after API call:
```python
elapsed = _time.monotonic() - t0
_llm_log.info("OPENAI_CALL_END call_n=%d elapsed=%.1fs", call_n, elapsed)
```

### What does NOT change

- No timeout changes
- No client reuse
- No Redis removal
- No changes to any other file

### How to run

```bash
.venv/bin/python runner.py --config configs/smoke_5.4mini_5mini_eval.yaml 2>&1 | tee /tmp/proof_run.log
```

### How to diagnose when it hangs

```bash
grep "OPENAI_CALL_" /tmp/proof_run.log | tail -5
```

### Interpretation

| Last log line | Diagnosis |
|---|---|
| `OPENAI_CALL_START call_n=N` (no matching CALL_END) | API call hung. Hypothesis confirmed. Proceed to Phase 2. |
| `OPENAI_CALL_END call_n=N` (no next CALL_START, no progress) | Hang is between API calls (parsing, eval, logging, Redis). Need more instrumentation. |
| All pairs matched, but gaps grow over time | Slowdown, not hang. Resource pressure. Different investigation needed. |

---

## Phase 2 — Minimal Fix (only after Phase 1 confirmation)

### Precondition

Phase 1 must show last log line is `OPENAI_CALL_START` with no matching `CALL_END`.

### What changes

One line in `llm.py:_openai_call()`:

```python
# Current:
client = OpenAI(api_key=api_key)

# Changed:
client = OpenAI(api_key=api_key, timeout=120.0)
```

This reduces the SDK default timeout from 600s to 120s. Sets httpx connect +
read + write + pool timeouts to 120s each.

### Limitation

This is a per-read-chunk timeout, not a hard wall-clock timeout. A server
slow-dripping one byte every 119s would not trigger it. Phase 1 timing data
will show whether this matters in practice.

### Confirmation signal

Run the same 116-eval experiment. If it completes (possibly with 1-2 timeout
failures scored as eval failures), the fix worked.

---

## Post-Fix Cleanup (after Phase 2 confirmed)

These are separate from the hang fix. Each done independently.

1. **Remove Redis from hot path** — delete the Redis try/import/emit block
   from `execution.py:_emit_metrics_event()`. Redis is optional instrumentation
   and unproven safe in the evaluation hot path.

2. **Reuse single OpenAI client** — create module-level singleton instead of
   per-call construction. Eliminates connection pool accumulation. Good hygiene,
   not the hang fix.

---

## Architecture Constraints

- No threads. The system is single-process, single-threaded, serial execution.
- No ThreadPoolExecutor. Removed in v3 pipeline redesign.
- No signal.alarm wrappers. Unnecessary complexity.
- No speculative fixes. Evidence before engineering.
