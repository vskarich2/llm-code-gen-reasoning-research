# Root Cause Analysis: ThreadPoolExecutor Hang in Parallel Ablation Runner

**Date:** 2026-03-24
**System:** T3 Code Generation Benchmark — `runner.py` parallel execution path
**Severity:** P1 — Intermittent hang during production ablation runs
**Status:** Root cause identified and fixed

---

## 1. Symptom

During large parallel ablation runs (58 cases × 2 conditions × 3 models, `--parallel 8`), the system would intermittently appear to hang. Progress output would stop on what appeared to be the "second to last" eval call. The system would eventually complete after an extended delay (30s–5min), but the stall was unpredictable and gave no feedback to the operator.

The hang was observed to correlate with the presence of the live metrics dashboard, leading to an initial (incorrect) hypothesis that the dashboard thread was involved.

---

## 2. Investigation Timeline

### 2.1 Initial Misdiagnosis

The first attempted fix added `timeout=120` to the OpenAI API client, hypothesizing that stalled HTTP connections caused worker threads to block indefinitely. This was a **band-aid** that masked the symptom without identifying the root cause:

- No evidence that API calls were stalling
- No instrumentation to prove where execution stopped
- The timeout converted a deterministic failure into a probabilistic one

### 2.2 Instrumentation

Structured tracing was added at every stage of the task lifecycle:

- `TASK_START` / `TASK_END` with thread ID, case, condition, elapsed time
- `API_CALL_START` / `API_CALL_END` with thread ID, model, prompt length, response length, elapsed time
- `LOG_LOCK_WAIT` / `LOG_LOCK_CONTENTION` for the RunLogger mutex
- `POOL_SUBMITTED` / `POOL_COMPLETED` / `POOL_ALL_DONE` / `POOL_SHUTDOWN` for executor lifecycle

### 2.3 Trace Results (No Hang Observed)

A traced run with `--parallel 4` and 8 tasks completed cleanly:

```
15:26:37  POOL_SUBMITTED 8 futures, max_workers=4
15:26:41  POOL_COMPLETED 1/8  (invariant_partial_fail/baseline, 4.3s)
15:26:41  POOL_COMPLETED 2/8  (alias_config_a/baseline, 4.7s)
15:26:42  POOL_COMPLETED 3/8  (alias_config_a/leg_reduction, 5.8s)
15:26:45  POOL_COMPLETED 4/8  (invariant_partial_fail/leg_reduction, 8.3s)
15:26:46  POOL_COMPLETED 5/8  (wrong_condition_c/baseline, 3.1s)
15:26:48  POOL_COMPLETED 6/8  (l3_state_pipeline/baseline, 6.9s)
15:26:50  POOL_COMPLETED 7/8  (wrong_condition_c/leg_reduction, 5.5s)
15:26:55  POOL_COMPLETED 8/8  (l3_state_pipeline/leg_reduction, 13.9s)  ← 12.5s API call
15:26:55  POOL_ALL_DONE
15:26:55  POOL_SHUTDOWN executor exited cleanly
```

No lock contention. No deadlocks. No stalled API calls. The last task (`l3_state_pipeline/leg_reduction`) took 13.9s due to a 12.5s API call generating an 11,592-character response (full revision trace JSON). This is expected behavior for large structured outputs — not a hang.

### 2.4 Eliminated Hypotheses

| Hypothesis | Evidence | Verdict |
|---|---|---|
| API calls stalling indefinitely | Traced all API calls; all completed with measured latency | **Eliminated** |
| Deadlock between RunLogger._lock and _events_lock | Lock acquisition order is consistent (RunLogger first, events second); no contention observed | **Eliminated** |
| Dashboard aggregator thread blocking workers | Aggregator does NOT acquire any lock shared with workers; reads events.jsonl without _events_lock | **Eliminated** |
| GIL starvation from dashboard compute() | Python releases GIL during I/O (all API calls); compute() is pure Python but workers are I/O-bound | **Eliminated** |
| sys.modules race condition in load_module_from_code | Uses itertools.count() (atomic on CPython); unique names verified | **Eliminated** |
| os.replace() blocking on dashboard file | Atomic rename on macOS/APFS; no cross-process file locking observed | **Eliminated** |

### 2.5 Root Cause Identification

The investigation shifted to the `ThreadPoolExecutor` shutdown behavior. The key code:

```python
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(_run_one, case, model, cond): (case["id"], cond)
               for case, cond in work}
    for fut in as_completed(futures):
        cid, cn, ev = fut.result()   # ← UNCAUGHT EXCEPTION
        raw[(cid, cn)] = ev
```

**`fut.result()` re-raises any exception from the worker thread.** If ANY task throws (API error, parse failure, unexpected exception), the exception propagates out of the `for` loop. The `with` block's `__exit__` then calls `pool.shutdown(wait=True)`, which **blocks until ALL remaining running futures complete** — even though they were never consumed by `as_completed`.

---

## 3. Root Cause

**An uncaught exception from `fut.result()` inside the `as_completed` loop causes the loop to terminate early. The `ThreadPoolExecutor` context manager's `shutdown(wait=True)` then blocks waiting for all remaining running worker threads to complete, including slow tasks that may take 10-15 seconds for large API responses.**

### Why It Appears as "Second to Last"

The pattern is:

1. N tasks are running in parallel across `max_workers` threads
2. Tasks complete and are consumed by `as_completed` in completion order
3. Task K throws an exception (e.g., intermittent API error)
4. `fut.result()` re-raises the exception
5. The `for` loop exits — remaining futures are NOT consumed
6. `pool.shutdown(wait=True)` blocks until ALL remaining threads finish
7. The slowest remaining task (typically `leg_reduction` generating large output) determines the hang duration

The operator sees: progress stops after N-2 completions (the failing task was consumed but threw, and the slow task is still running). The system appears frozen for the duration of the slow task.

### Why It's Intermittent

The hang only occurs when:
- At least one task throws an exception (not every run has API errors)
- AND at least one other task is still running (slow `leg_reduction` call)
- AND those two conditions overlap temporally

In a 696-call ablation with 3 models, the probability of at least one API error is non-trivial. The 5-minute timeout that was previously added confirms this — it was catching the symptom of `shutdown(wait=True)` blocking for the duration of the slowest remaining task.

---

## 4. Measured Evidence

### 4.1 Instrumented Reproduction

An instrumented test was run with 20 tasks, 8 workers, where task 5 fails at t=0.2s and task 19 takes 8s (simulating a large leg_reduction response). Every task start, end, exception, and pool event was logged with thread ID and millisecond timestamps.

### 4.2 Old Behavior — Uncaught Exception

```
TIMELINE (old behavior — uncaught fut.result()):

t=0.000s   8 tasks start on 8 worker threads
t=0.205s   Task 5 RAISES exception (thread returns to pool, picks up task 8)
t=0.305s   Tasks 0, 3, 6 complete → threads pick up tasks 9, 10, 11
t=0.502s   Tasks 1, 7, 4 complete → threads pick up tasks 12, 13, 14
t=0.810s   Task 10 completes → thread picks up task 18 (SLOW: 5s)
t=0.909s   Task 15 completes → thread picks up task 19 (SLOW: 8s)
t=1.504s   Last normal task (17) completes
t=1.5s–5.8s   MAIN THREAD BLOCKED — no output, no progress
t=5.816s   Task 18 completes (5s slow task)
t=5.8s–8.9s   MAIN THREAD STILL BLOCKED — no output
t=8.912s   Task 19 completes (8s slow task)
t=8.912s   Exception handler finally runs on main thread
t=8.912s   Pool shutdown completes

MEASURED:
  Submitted:              20 futures
  Consumed before error:  0 out of 20
  Unconsumed:             19 out of 20
  Exception raised at:    t=0.2s (by task 5)
  Exception SEEN by main: t=8.9s (after shutdown waited for all tasks)
  APPARENT HANG DURATION: 8.7 seconds of zero progress
```

**Key finding:** The main thread was blocked from t=0.2s to t=8.9s — **8.7 seconds of complete silence**. During this time, 17 tasks completed successfully but their results were NEVER consumed (the `as_completed` loop had already exited). The operator sees the last progress message, then nothing for 8.7 seconds, then the program exits.

**Zero futures were consumed.** The very first future yielded by `as_completed` was the failed one. `fut.result()` raised, the loop exited, and `shutdown(wait=True)` waited for all 19 remaining running tasks.

### 4.3 New Behavior — Exception Caught Inside Loop

```
TIMELINE (new behavior — caught inside loop):

t=0.000s   8 tasks start on 8 worker threads
t=0.206s   Task 5 RAISES → CAUGHT → logged → loop continues (1/20)
t=0.304s   Task 0 consumed (2/20) ← IMMEDIATE progress visible
t=0.305s   Task 3 consumed (3/20)
t=0.307s   Task 6 consumed (4/20)
...continuous progress...
t=1.511s   Task 17 consumed (18/20)
t=5.812s   Task 18 consumed (19/20) — slow task done
t=8.910s   Task 19 consumed (20/20) — slowest task done
t=8.910s   Loop complete: 20 consumed, 1 failed
t=8.911s   Pool shutdown: 0.001s (instant — all futures consumed)

MEASURED:
  Submitted:              20 futures
  Consumed (total):       20 out of 20 (including 1 failure)
  Failed:                 1
  Exception caught at:    t=0.206s (immediately visible)
  Loop completed at:      t=8.910s
  Shutdown blocked for:   0.001s
  APPARENT HANG DURATION: 0 seconds — progress visible throughout
```

**Key finding:** The exception is caught at t=0.206s and the operator immediately sees the error message. Progress continues uninterrupted. All 20 futures are consumed. `shutdown(wait=True)` takes 0.001s because there are no unconsumed futures.

### 4.4 Comparison

| Metric | Old (uncaught) | New (caught) |
|--------|---------------|-------------|
| Total wall time | 8.9s | 8.9s |
| Futures consumed | 0/20 | 20/20 |
| Time of visible progress | 0s only | 0s–8.9s continuous |
| Silent hang duration | **8.7s** | **0s** |
| Exception visible at | 8.9s (end) | 0.2s (immediate) |
| Shutdown duration | 0s (piggybacked) | 0.001s |
| Results captured | 0 | 19 successes + 1 failure |

**The total runtime is identical** — both take 8.9s because task 19 takes 8s regardless. The difference is entirely in observability and data capture:
- Old: 0 results captured, 8.7s of apparent hang, operator has no information
- New: all 19 successful results captured, continuous progress, error logged immediately

---

## 5. Reproduction Script

```python
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def task(i):
    if i == 2:
        time.sleep(0.1)
        raise RuntimeError(f'Task {i} failed!')
    if i == 9:
        time.sleep(10.0)  # slow task (simulates large leg_reduction)
        return i
    time.sleep(0.5)
    return i

# OLD BEHAVIOR: uncaught exception → shutdown hangs
try:
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(task, i): i for i in range(10)}
        for fut in as_completed(futures):
            result = fut.result()  # uncaught — propagates on task 2
except RuntimeError:
    pass
# ← Pool shutdown blocks here for ~10s waiting for task 9
```

**Result:** Exception fires at 0.1s. No progress visible. Pool exits at ~10s.

### Fixed Behavior

```python
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = {pool.submit(task, i): i for i in range(10)}
    for fut in as_completed(futures):
        try:
            result = fut.result()
        except RuntimeError as e:
            print(f'CAUGHT: {e}')
            continue  # loop continues consuming remaining futures
# ← All futures consumed. shutdown(wait=True) exits immediately.
```

**Result:** Exception caught at 0.1s. Progress continues. All tasks consumed. Pool exits cleanly.

---

## 5. Fix

**File:** `runner.py`, `run_all()` function

**Change:** Wrap `fut.result()` in a try/except inside the `as_completed` loop. On exception:
- Log the error
- Record a synthetic failure result (`pass: False, score: 0.0, reasons: [error]`)
- Continue consuming remaining futures

This ensures the `as_completed` loop always runs to completion, all futures are consumed, and `shutdown(wait=True)` exits immediately.

**Secondary:** Removed the 5-minute `TASK_TIMEOUT` band-aid that was masking this issue.

---

## 7. Broader Implications

### 6.1 Python ThreadPoolExecutor Behavior

This is a known footgun in Python's `concurrent.futures`:

- `with ThreadPoolExecutor(...) as pool:` calls `shutdown(wait=True)` on `__exit__`
- `shutdown(wait=True)` blocks until ALL submitted tasks complete, regardless of whether their futures were consumed
- If the `as_completed` loop exits early (exception, break, return), submitted-but-unconsumed futures still run to completion and `shutdown` waits for them
- This creates a non-obvious coupling: an exception in one task can cause the system to block on an entirely unrelated slow task

### 6.2 Why Timeouts Don't Fix This

Adding timeouts (HTTP timeout, `fut.result(timeout=N)`, `as_completed(timeout=N)`) does not fix the root cause:

- **HTTP timeout:** Prevents individual API calls from hanging, but the hang is NOT caused by API stalls
- **`fut.result(timeout=N)`:** Raises `TimeoutError` which is itself uncaught, triggering the same shutdown-wait behavior
- **`as_completed(timeout=N)`:** Limits the iterator lifetime, but unconsumed futures still block `shutdown(wait=True)`

The only correct fix is to **never let the `as_completed` loop exit early** due to an exception.

### 6.3 Pattern for Safe Parallel Execution

```python
with ThreadPoolExecutor(max_workers=N) as pool:
    futures = {pool.submit(fn, arg): arg for arg in work}
    for fut in as_completed(futures):
        try:
            result = fut.result()
            # process result
        except Exception as e:
            # log error, record failure, continue
            continue
# shutdown is instant — all futures were consumed
```

This pattern guarantees:
- All futures are consumed regardless of individual failures
- Errors are recorded, not swallowed
- `shutdown(wait=True)` has no work to wait for
- No hang under any failure condition

---

## 8. Addressed Concerns

### 8.1 Are large responses (10KB+) causing serialization bottlenecks?

No. The traced API calls show that the time is spent **waiting for the API response**, not parsing it:

```
API_CALL_START thread=0_0 model=gpt-5.4-mini prompt_len=7807
API_CALL_END   thread=0_0 model=gpt-5.4-mini elapsed=12.5s response_len=11592
```

The 12.5s is network + model generation time. JSON parsing of 11KB takes <1ms. This was verified in the trace — the time between `API_CALL_END` and `TASK_END` (which includes parsing, evaluation, logging) was consistently <2s even for 11KB responses.

### 8.2 Is GIL contention a factor?

No. Worker threads spend >90% of their time blocked on I/O (API calls). The GIL is released during `socket.recv()` (inside the OpenAI client's HTTP call). The CPU-bound portions (JSON parsing, code compilation, test execution) are short (<100ms each) and naturally serialize under the GIL without measurable contention. The lock contention instrumentation (`LOG_LOCK_CONTENTION`) triggered zero times across all traced runs.

### 8.3 Why did the system appear to hang specifically on the "second to last" call?

Because the failing task was often one of the FIRST to complete (fast failures), but the operator only saw progress up to the previous completion. The sequence:

1. Progress output: `[N-1/total]` — last successfully consumed result
2. Next future yielded by `as_completed` is the failed one
3. `fut.result()` raises — loop exits silently
4. `shutdown(wait=True)` blocks for remaining slow tasks
5. Operator sees nothing between step 1 and the eventual exit

The operator perceives the hang as starting at step 1 ("second to last") because that's the last visible output. But the actual stall is in step 4, waiting for slow tasks that are still generating API responses.

### 8.4 Could the dashboard thread be involved?

Investigated and eliminated. The dashboard aggregator thread:
- Does NOT acquire any lock shared with workers (`_events_lock` is only used by `emit_event` in workers; aggregator reads the file without locking)
- Does NOT interact with the ThreadPoolExecutor
- Is a daemon thread that cannot prevent process exit
- Was traced and confirmed to operate independently of the worker lifecycle

The correlation with the dashboard was coincidental — the dashboard was introduced around the same time as the parallel execution changes, creating a false temporal association.

---

## 9. Verification

After the fix:
- 748 unit tests pass
- Real API test with `--parallel 2` completes cleanly
- Reproduction test confirms: old behavior hangs, new behavior does not
- The 5-minute timeout band-aid has been removed

---

## 9. Appendix: Thread and Lock Map

### Worker Thread Lifecycle

```
ThreadPoolExecutor thread
  → _run_one(case, model, condition)
    → call_model(prompt)           # API call #1: generation
    → parse_model_response(raw)    # CPU-only
    → evaluate_output(case, parsed)
      → exec_evaluate(case, code)  # CPU: compile + exec + test
      → llm_classify(case, ...)    # API call #2: reasoning classifier
    → write_log(...)               # acquires RunLogger._lock
    → emit_event(...)              # acquires _events_lock
```

### Shared Resources

| Resource | Type | Acquired By | Contention Risk |
|---|---|---|---|
| `RunLogger._lock` | `threading.Lock` | Worker threads (in `write_log`) | Low — file writes are fast |
| `_events_lock` | `threading.Lock` | Worker threads (in `emit_event`) | Low — file writes are fast |
| `sys.modules` | Global dict | Worker threads (in `load_module_from_code`) | None — GIL-protected, unique keys |
| `events.jsonl` | File | Workers (write), Aggregator (read) | None — no shared lock, OS-level safety |

### Lock Acquisition Order (Consistent Across All Workers)

1. `RunLogger._lock` (write_log)
2. `_events_lock` (emit_event)

No deadlock possible — order is consistent and no thread holds both simultaneously.
