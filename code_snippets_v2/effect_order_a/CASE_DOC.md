# Case: effect_order_a

**Family:** effect_order
**Difficulty:** A (Easy)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F2: Ecological fallacy (batch != per-item)

---

## Task Prompt

> Refactor this event processor for clarity. Return the updated code.

## What the Code Does

A single-file batch processor (`processor.py`) maintains a running `_counter` and a `_snapshots` list. The intent is that after processing each item in a batch, a snapshot of the current counter value is recorded.

Key code in `processor.py`:

```python
def process_batch(items):
    global _counter
    for item in items:
        _counter += item
    # BUG: snapshot only once at end, not per-item
    snapshot()
    return _counter
```

`snapshot()` appends the current `_counter` value to `_snapshots`. For a 3-item batch, the contract requires 3 snapshots -- one after each item is accumulated.

## The Bug

`snapshot()` is called once after the loop completes instead of once per iteration inside the loop. For a batch of 3 items, only 1 snapshot is recorded instead of 3. The bug is silent -- no exception, no wrong return type -- but the invariant "one snapshot per item" is violated.

## The Correct Fix

Move `snapshot()` inside the loop:

```python
def process_batch(items):
    global _counter
    for item in items:
        _counter += item
        snapshot()  # moved inside loop
    return _counter
```

**Lines changed:** 2 (move `snapshot()` call into loop body, adjust indentation)

## What the Test Checks

1. Reset module state (`_counter = 0`, `_snapshots = []`)
2. Call `process_batch([10, 20, 30])`
3. **Assert:** `len(get_snapshots()) == 3` -- one snapshot per item

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity," not "fix a bug." An LLM may reorganize code without noticing the placement of `snapshot()` matters.
- The code runs without errors regardless of snapshot placement. There is no crash or exception to signal the problem.
- Batch-level operations often look like intentional optimizations ("snapshot once at the end"), creating an ecological fallacy where batch-level behavior is mistaken for correct per-item behavior.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug and its effect are visible within a single function body. Reading `process_batch` and seeing that `snapshot()` is outside the loop (while the docstring says "snapshot after each") requires only local pattern matching -- associating the loop structure with the snapshot call placement.

### Trap Type: F2: Ecological fallacy (batch != per-item)

The batch-level snapshot looks reasonable at a glance -- you process items, then record the final state. The ecological fallacy is assuming that a single batch-level snapshot is equivalent to per-item snapshots. It is not: the snapshot count must equal the item count.

### Why This Case Is L1, Not L2 or L3

**Not L2** because the entire bug, its cause, and the violated invariant are visible in one function in one file. No cross-function or cross-file reasoning is needed. `snapshot()` is defined in the same file and its behavior is trivial (appends to a list).

**Not L3** because there is no multi-step state evolution or temporal ordering constraint to reason about. The fix is a single structural change (move one line inside a loop).

## Failure Mode Being Tested

**SIDE_EFFECT_ORDER** (hidden_dependency) -- a side effect that should happen per-item is incorrectly batched. The ecological fallacy (F2) creates a mismatch between the granularity of processing and the granularity of observation.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May recognize snapshot should be per-item but fail to actually move it |
| 4o-mini | Heuristic | Likely to notice the loop/snapshot mismatch but may refactor away the bug |
| 5-mini | CSF | Should detect and fix the single-line placement issue |
