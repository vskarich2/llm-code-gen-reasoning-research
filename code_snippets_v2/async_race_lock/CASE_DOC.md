# Case: async_race_lock

**Family:** Race Condition
**Difficulty:** Hard (V1)
**Bug Pattern:** RACE_CONDITION
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F6 Mechanism: replace process_item with quick_increment, removing the lock guard that run_verified depends on

---

## Task Prompt

> process_item and quick_increment both increment the counter. Simplify by using quick_increment everywhere and removing the locking overhead. Return the updated code.

## What the Code Does

The system has four modules implementing a counter with locking:

- **state.py** manages a global counter with a lock:
  ```python
  _counter = {"value": 0, "locked": False}
  def try_lock():     # Returns False if already locked
  def unlock():       # Releases lock
  def increment(n=1): # Adds n to counter
  def get_counter():  # Returns current value
  ```

- **worker.py** provides two increment strategies:
  - `process_item(item)` -- acquires lock, reads counter before, increments, reads counter after, unlocks. Returns `{"status": "ok", "before": X, "after": Y}`.
  - `quick_increment(item)` -- just calls `increment(item["weight"])`. Returns `{"status": "ok"}` with no before/after.

- **scheduler.py** orchestrates pipelines:
  - `run_pipeline(items)` -- uses `process_batch_serial` (which calls `process_item`).
  - `run_fast_pipeline(items)` -- uses `quick_increment` directly.
  - `run_verified(items)` -- uses `process_batch_serial` (which calls `process_item`), then verifies `get_counter() == sum(weights)`.

- **api.py** exposes `handle_request` (calls `run_pipeline`) and `handle_verified_request` (calls `run_verified`).

## The Bug

The buggy version (`worker_buggy.py`) replaces `process_item` with the body of `quick_increment`:

```python
def process_item(item):
    increment(item["weight"])
    return {"status": "ok"}     # No lock, no before/after
```

This causes two problems:
1. **Lost lock guard:** `process_item` no longer acquires/releases the lock, making concurrent access unsafe.
2. **Missing before/after fields:** `run_verified` calls `process_batch_serial` which calls `process_item`. The test checks that each result has `"before"` and `"after"` keys, proving that the locked version was used. Without these fields, the verified pipeline silently degrades.

## The Correct Fix

The reference fix (`reference_fixes/async_race_lock.py`) preserves the original `process_item` with full locking:

```python
def process_item(item):
    if not try_lock():
        return {"status": "skipped", "reason": "locked"}
    before = get_counter()
    increment(item["weight"])
    after = get_counter()
    unlock()
    return {"status": "ok", "before": before, "after": after}
```

The key insight: `process_item` and `quick_increment` are NOT interchangeable. `process_item` provides atomic read-increment-read with locking; `quick_increment` is a fire-and-forget increment. Different callers need different guarantees.

## What the Test Checks

1. Resets counter state.
2. Calls `run_verified([{"weight": 1}, {"weight": 1}, {"weight": 1}, {"weight": 1}, {"weight": 1}])`.
3. Checks `result["total"] == 5` (counter integrity).
4. Checks each result in `result["results"]` has both `"before"` and `"after"` keys, proving `process_item` with locking was used (not `quick_increment`).

If `process_item` is replaced with `quick_increment`'s logic, the results lack `"before"` and `"after"`, and the test fails.

## Why This Is Difficult for LLMs

1. **The task explicitly instructs removal:** "Simplify by using quick_increment everywhere and removing the locking overhead." The model is told to do exactly the wrong thing.

2. **Locking seems like premature optimization:** In a serial execution context (which this appears to be), locking looks unnecessary. The model reasons "this is single-threaded, locks are overhead" and removes them.

3. **The before/after contract is implicit:** Nothing in the function signatures or docstrings says "results must include before/after fields." This contract is enforced only by `run_verified` in `scheduler.py` and the test -- two hops away from `process_item`.

4. **Two functions with same effect, different contracts:** Both `process_item` and `quick_increment` increment the counter by the same amount. The difference is purely in side-channel information (before/after, lock state) that doesn't affect the counter value.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about the intervention of replacing `process_item` with `quick_increment`:

1. Trace `run_verified` -> `process_batch_serial` -> `process_item` to understand the call chain.
2. Recognize that `process_item` returns `{"before": X, "after": Y}` while `quick_increment` returns only `{"status": "ok"}`.
3. Trace how `run_verified` uses the results and what the verified invariant requires.
4. Understand that the lock mechanism provides atomicity guarantees for concurrent scenarios, even if the serial test doesn't directly exercise concurrency.

### Trap Type: F6 Mechanism

**F6 (Mechanism):** The model must understand the mechanism of locking -- why `try_lock`/`unlock` exists, what invariant it protects (atomic read-increment-read), and what the `before`/`after` fields provide (proof of atomicity). Without understanding this mechanism, the lock appears as pure overhead with no functional purpose.

The mechanism trap is compounded by the serial execution context: in a single-threaded test, the lock never contends, so the model cannot observe contention-based failures. The lock's purpose is prophylactic (guarding against concurrency) and informational (providing before/after snapshots), neither of which manifests as a visible failure in serial execution unless you check the result structure.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug requires tracing through `scheduler.py` -> `worker.py` -> `state.py` to understand the locking mechanism, then back through the result format to understand the verification contract.
- **Not L3 (counterfactual):** The reasoning is forward-traceable: "If I replace process_item with quick_increment, the results no longer have before/after fields, and run_verified (or its callers) breaks." No counterfactual about alternative designs is needed.
- **L2 (deep intervention):** The model must simulate the intervention (replacing process_item), trace the multi-step causal chain through the scheduler and the result format, and identify the contract violation.

## Failure Mode Being Tested

RACE_CONDITION -- Removing the lock from the processing path eliminates the atomic read-increment-read guarantee. While the immediate test failure is about missing before/after fields (a structural check), the underlying failure mode is loss of concurrency safety.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will follow the task prompt and replace process_item with quick_increment |
| 4o-mini | CSF | Likely removes locking as "overhead" per the task prompt; may not trace the before/after contract |
| 5-mini | CSF | May notice the before/after fields but likely still follows the task prompt to simplify |
