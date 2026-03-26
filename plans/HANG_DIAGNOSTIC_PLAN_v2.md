# Hang Diagnostic Plan v2

**Date:** 2026-03-26
**Supersedes:** HANG_DIAGNOSTIC_PLAN_v1.md
**Problem:** Runner hangs at ~108/116 evaluations during ablation runs.

---

## Root Cause Hypothesis

`client.responses.create()` in `llm.py:_openai_call()` stalls on an OpenAI API
response. The SDK default timeout is `Timeout(connect=5.0, read=600, write=600,
pool=600)`. A single stalled call blocks the serial process for up to 10 minutes.
Multiple stalls compound. By eval 108, 216+ API calls have been made — the
probability of hitting stalls that appear as a hang is non-trivial.

Additionally, a new `OpenAI()` client is constructed on every call (216+ instances),
each with its own httpx connection pool. This is a resource leak that may increase
stall probability, but it is NOT the primary hypothesis — it is a separate concern.

This is a hypothesis. Phase 1 proves or disproves it.

---

## Phase 1 — Instrumentation (no behavior change)

### What changes

One file: `llm.py:_openai_call()`. Instrumentation wrapping both the client
construction and the API call, plus an exception path.

### Log lines added

All log lines include `call_n`, `model`, and context from the call_logger's
`_call_context` (which carries `case_id`, `condition`, `attempt_index`).

```
OPENAI_CLIENT_CREATE_START  call_n={N} model={M}
OPENAI_CLIENT_CREATE_END    call_n={N} elapsed={T}s
OPENAI_CALL_START           call_n={N} model={M} case_id={C} condition={D} prompt_len={L}
OPENAI_CALL_END             call_n={N} model={M} elapsed={T}s response_len={L}
OPENAI_CALL_EXCEPTION       call_n={N} model={M} elapsed={T}s error={E}
```

### Concrete code (instrumentation only)

```python
_call_counter = itertools.count(1)

def _openai_call(prompt: str, model: str, api_key: str) -> str:
    from openai import OpenAI
    import time as _t

    call_n = next(_call_counter)

    # Read context set by execution.py via set_call_context()
    from call_logger import _call_context
    ctx_case = _call_context.get("case_id", "?")
    ctx_cond = _call_context.get("condition", "?")

    # Client construction
    _llm_log.info("OPENAI_CLIENT_CREATE_START call_n=%d model=%s", call_n, model)
    t_create = _t.monotonic()
    temperature, top_p = _get_model_spec(model)
    client = OpenAI(api_key=api_key)
    _llm_log.info("OPENAI_CLIENT_CREATE_END call_n=%d elapsed=%.3fs", call_n, _t.monotonic() - t_create)

    kwargs = dict(model=model, input=prompt, store=False)
    try:
        from experiment_config import get_config
        no_temp = get_config().models.no_temperature_prefixes
    except (RuntimeError, ImportError):
        no_temp = ("o1", "o3", "o4", "gpt-5")
    if not any(model.startswith(p) for p in no_temp):
        kwargs["temperature"] = temperature

    # API call
    _llm_log.info("OPENAI_CALL_START call_n=%d model=%s case_id=%s condition=%s prompt_len=%d",
                   call_n, model, ctx_case, ctx_cond, len(prompt))
    t_call = _t.monotonic()
    try:
        response = client.responses.create(**kwargs)
    except Exception as e:
        elapsed = _t.monotonic() - t_call
        _llm_log.error("OPENAI_CALL_EXCEPTION call_n=%d model=%s case_id=%s condition=%s elapsed=%.1fs error=%s",
                        call_n, model, ctx_case, ctx_cond, elapsed, e)
        raise

    elapsed = _t.monotonic() - t_call
    _llm_log.info("OPENAI_CALL_END call_n=%d model=%s elapsed=%.1fs response_len=%d",
                   call_n, model, elapsed, len(response.output_text))
    return response.output_text
```

### What does NOT change

- No timeout values changed
- No client reuse
- No Redis removal
- No changes to execution.py, runner.py, evaluator.py, or any other file
- `call_model()` wrapper and `_emit_call_log()` remain unchanged

### How to run

```bash
.venv/bin/python runner.py --config configs/smoke_5.4mini_5mini_eval.yaml 2>&1 | tee /tmp/proof_run.log
```

### How to diagnose when it hangs

```bash
grep "OPENAI_" /tmp/proof_run.log | tail -10
```

### Interpretation table

| Last log line | Diagnosis | Next action |
|---|---|---|
| `OPENAI_CLIENT_CREATE_START call_n=N` (no CREATE_END) | Client construction hung — resource exhaustion or httpx pool stall | Investigate FD count, client reuse is the fix |
| `OPENAI_CLIENT_CREATE_END call_n=N` (no CALL_START) | Hang between client creation and API call — kwargs construction or config lookup | Inspect the intermediate code |
| `OPENAI_CALL_START call_n=N` (no CALL_END, no EXCEPTION) | API call hung — no response from server within SDK timeout | Proceed to Phase 2 (reduce timeout) |
| `OPENAI_CALL_EXCEPTION call_n=N` followed by silence | Exception raised but caller hung processing it | Inspect call_model exception handling |
| `OPENAI_CALL_END call_n=N` followed by silence | Hang is AFTER the API call — in parsing, evaluation, logging, or Redis | Add instrumentation to downstream code |
| All pairs matched, CREATE_END elapsed times grow | Client construction slowing — connection pool pressure | Client reuse is the fix |
| All pairs matched, CALL_END elapsed times grow | API calls slowing — rate limiting or server degradation | May not be a hang, just slowdown |

---

## Phase 2 — Minimal Containment Change (only after Phase 1 confirmation)

### Precondition

Phase 1 must show last log line is `OPENAI_CALL_START call_n=N` with no matching
`CALL_END` or `CALL_EXCEPTION`. This confirms the API call is the stall point.

### What changes

One line in `llm.py:_openai_call()`:

```python
# Current:
client = OpenAI(api_key=api_key)

# Changed:
client = OpenAI(api_key=api_key, timeout=120.0)
```

This changes the SDK timeout from `Timeout(connect=5.0, read=600, write=600,
pool=600)` to `Timeout(connect=120.0, read=120.0, write=120.0, pool=120.0)`.

### Limitation

`timeout=120.0` sets per-read-chunk timeout, not total wall-clock timeout.
A server slow-dripping bytes every <120s would not trigger it. Phase 1 timing
data (elapsed values in CALL_END logs) will show whether actual stalls are
zero-byte idle stalls (caught by read timeout) or slow-drip stalls (not caught).
This determines whether 120.0 is sufficient containment.

### Why this is containment, not a proven fix

Reducing 600s to 120s bounds the maximum stall duration for the most common
failure mode (idle connection, zero bytes). It does not eliminate all possible
stall modes. It is the minimum change needed to determine whether the hypothesis
is correct in production conditions.

---

## Timeout Failure Semantics

### Exception raised on timeout

The OpenAI SDK raises `openai.APITimeoutError`, which is a subclass of
`openai.APIConnectionError` -> `openai.APIError` -> `Exception`.

Verified:
```
>>> openai.APITimeoutError.__mro__
(APITimeoutError, APIConnectionError, APIError, OpenAIError, Exception, BaseException, object)
```

### Where it propagates

```
_openai_call()          raises APITimeoutError
  ↓
call_model()            catches Exception, calls _emit_call_log(error=str(e)), re-raises
  ↓
_attempt_and_evaluate() does NOT catch — propagates
  ↓
run_single()            does NOT catch — propagates
  ↓
_run_one()              catches Exception, logs TASK_FAILED, RE-RAISES
  ↓
run_all()               does NOT catch — CRASHES THE ENTIRE RUN
```

### Current behavior on timeout (PROBLEM)

A timeout exception in ANY evaluation crashes the entire run. `run_all()` has
no try/except around `_run_one()`. All subsequent cases are lost. The run log
has no end_time marker. Events already written are preserved, but the run is
incomplete.

### Required failure semantics (Phase 2 must also address)

A timeout on one evaluation must NOT crash the run. Required behavior:

1. `_openai_call()` raises `APITimeoutError`
2. `call_model()` logs the error via `_emit_call_log()` and re-raises (existing behavior — correct)
3. The exception propagates to `_run_one()` which logs `TASK_FAILED` (existing behavior — correct)
4. **`run_all()` must catch the exception and record a terminal failure for that (case, condition) pair** — THIS DOES NOT EXIST YET

The terminal failure record must contain:
- `pass: False`
- `score: 0.0`
- `error_type: "api_timeout"` (or `"task_exception"` generically)
- `reasons: ["API timeout after Ns: {error message}"]`
- The case must appear in final results with this failure record
- No retry. One attempt, one failure, move on.

5. `write_log()` must be called for the timed-out case (so the failure is in the JSONL log)
6. `_emit_metrics_event()` must be called (so the failure appears in events)

### WAL / checkpoint integration

- Every timed-out evaluation produces a complete failure record in the run log.
  There is no undefined state — the case is explicitly marked failed with
  `error_type: "api_timeout"`.
- Resume behavior: if a future resume system skips already-completed cases,
  timed-out cases are "completed with failure" — they are NOT retried on resume
  unless explicitly requested. The failure record is terminal.
- The run always completes (reaches `close_run_log()`) even if some evals timeout.
  The run metadata gets `end_time`, `events_written`, and `log_valid`.

---

## Phase 2 — Complete Change Set

Phase 2 consists of exactly TWO changes, both in service of one goal: a timed-out
API call produces a failure record and the run continues.

### Change 1: Reduce timeout in `llm.py:_openai_call()`

```python
client = OpenAI(api_key=api_key, timeout=120.0)
```

### Change 2: Catch exceptions in `runner.py:run_all()`

```python
for i, (case, cond) in enumerate(work):
    try:
        cid, cn, ev = _run_one(case, model, cond)
    except Exception as e:
        cid = case["id"]
        cn = cond
        _log.error("TASK_EXCEPTION case=%s cond=%s: %s", cid, cn, e)
        ev = {
            "pass": False, "score": 0.0,
            "reasons": [f"task_exception: {e}"],
            "error_type": "task_exception",
            "failure_modes": [],
            "execution": {"status": "error", "ran": False},
        }
    raw[(cid, cn)] = ev
    if not quiet:
        _print_progress(i + 1, total, cid, cn, ev)
```

This ensures:
- The timed-out case gets a failure record in `raw`
- The loop continues to the next case
- The failure appears in final results and is printed
- `write_log` and `_emit_metrics_event` are NOT called for the exception case
  (because they were never reached), but the failure IS recorded in the results
  dict which is used by `print_results()` and returned to the caller

### Why both changes are necessary

Change 1 alone would cause the timeout to crash the run (exception propagates
to `run_all()` which has no handler). Change 2 alone does nothing (no timeout
to trigger the exception). They are a single logical fix split across two call
sites.

---

## Hardening Tasks (separate from hang fix, each independent)

These are NOT cleanup. They are separate reliability improvements justified on
their own merits. Each is blocked on Phase 2 confirmation (the hang fix works).

### H1: Remove Redis from evaluation hot path

**Purpose:** Eliminate unproven network dependency from measurement code.
**File:** `execution.py:_emit_metrics_event()`
**Change:** Delete the Redis try/import/emit block.
**Justification:** Redis is optional instrumentation. It performs synchronous
network I/O (`ping()` + `xadd()`) on every evaluation. It has 1s timeouts so
it cannot cause infinite hangs, but it adds latency and is an unproven
dependency in code that determines experimental results.

### H2: Reuse single OpenAI client per process

**Purpose:** Eliminate connection pool accumulation from per-call client
construction.
**File:** `llm.py`
**Change:** Create module-level `_openai_client` singleton. Reuse across all
`_openai_call()` invocations.
**Justification:** Each `OpenAI()` client creates an httpx connection pool.
216+ pools across a run leak sockets and file descriptors. Reusing one client
with one pool eliminates this resource pressure. This does not fix the hang
(the timeout does that), but it reduces the probability of resource-pressure-
induced stalls.

---

## Architecture Constraints

- No threads. The system is single-process, single-threaded, serial execution.
- No ThreadPoolExecutor. Removed in v3 pipeline redesign.
- No signal-based timeout wrappers. Unnecessary complexity.
- No speculative fixes. Evidence before engineering.
- No silent fallbacks. Every failure produces a log record.
- No swallowed exceptions. Every `except` block either logs and re-raises, or
  logs and produces a terminal failure record.
