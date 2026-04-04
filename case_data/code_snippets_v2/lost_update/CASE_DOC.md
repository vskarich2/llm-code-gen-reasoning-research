# Case: lost_update

**Family:** concurrency
**Difficulty:** medium
**Bug Pattern:** read-modify-write race condition
**Causal Depth:** 2
**Pearl Level:** L2
**Trap Type:** F3: race as hidden shared state

---

## Task Prompt

> Fix the counter so that both sequential and interleaved double-increments produce a final value of 2.

## What the Code Does

`counter.py` implements a global counter (`_value`) with non-atomic read-modify-write increments, simulated deterministically via step functions.

`make_increment_steps()` splits an increment into two closures that share a `captured` dict:

```python
def step_read():
    captured["current"] = get()
    return ("read", captured["current"])

def step_write():
    _set(captured["current"] + 1)
    return ("write", captured["current"] + 1)
```

Two scenario functions execute two increments:
- `sequential_double_increment()`: runs read_a, write_a, read_b, write_b -- produces 2 (correct).
- `interleaved_double_increment()`: runs read_a, read_b, write_a, write_b -- both read 0, both write 1 (bug).

## The Bug

In `interleaved_double_increment()`, the step ordering is `[read_a, read_b, write_a, write_b]`. Both `step_read` closures execute before either `step_write`, so both capture `current = 0`. Both writes then set `_value = 0 + 1 = 1`. The second increment is silently lost.

The violated invariant: two increments must always produce `value = 2`, regardless of interleaving.

## The Correct Fix

The reference fix (`reference_fixes/lost_update.py`) makes each increment atomic by combining read and write into a single step:

```python
def make_increment_steps():
    def step_atomic_increment():
        current = get()
        _set(current + 1)
        return ("atomic_increment", current + 1)

    def step_noop():
        return ("noop",)

    return step_atomic_increment, step_noop
```

The function still returns two values to preserve the call-site interface, but the second step is a no-op. Under interleaving, the first atomic step reads 0 and writes 1, then the second atomic step reads 1 and writes 2.

## What the Test Checks

1. `sequential_double_increment()` must return 2.
2. `interleaved_double_increment()` must return 2.

Both assertions use strict equality (`!= 2`).

## Why This Is Difficult for LLMs

- **The interleaving is deterministic, not random.** There are no threads or locks. The bug is purely in the step ordering passed to `run_steps`. Models that associate concurrency bugs only with threading will miss this.
- **Common wrong fix: adding a lock.** There is no threading infrastructure. Adding `threading.Lock` does nothing because all steps run on one thread.
- **Common wrong fix: changing the step order.** Reordering the steps in `interleaved_double_increment` changes the test scenario rather than fixing the code.
- **The fix requires understanding closure capture.** The `captured` dict is shared state between `step_read` and `step_write`. The model must recognize that separating read and write into distinct schedulable units is the root cause.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention

The model must reason: "If I intervene by making read+write atomic (a single step), then even under the interleaved schedule, the second increment will see the result of the first." This is a counterfactual intervention on the code structure, not just observation (L1) of what happens.

### Trap Type: F3: race as hidden shared state

The hidden shared state is the global `_value` module variable. Each increment's `step_read` captures a snapshot into its own `captured` dict, but both snapshots reference the same global. The race is that two reads of the same global happen before either write, creating stale-read semantics. The "hidden" aspect is that `_value` is not passed as a parameter -- it is accessed through `get()` and `_set()`, obscuring the shared-state dependency.

### Why This Case Is L2, Not L1 or L3

- **Not L1:** L1 (association) would be recognizing "interleaved operations can cause bugs." That is insufficient here -- the model must identify which specific intervention (atomic step) prevents the lost update.
- **Not L3:** L3 (counterfactual) requires reasoning about structural vs. contingent causes or multiple independently necessary conditions. Here there is a single clear intervention point: make the increment atomic. No structural/contingent distinction or multi-factor but-for reasoning is needed.

## Failure Mode Being Tested

Read-modify-write race condition: two operations read the same pre-state, compute independently, and the second write overwrites the first's result.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely adds threading locks or reorders steps rather than merging read+write into one atomic step. |
| 4o-mini | partial | May recognize the stale-read problem but struggle with the step-function abstraction. Could try to add state checks rather than merging steps. |
| 5-mini | pass | Should identify the non-atomic read-write split and merge them, though may produce a slightly different structure than the reference fix. |
