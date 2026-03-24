# Case: effect_order_b

**Family:** effect_order
**Difficulty:** B (Medium)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F2: Ecological fallacy (batch != per-item)

---

## Task Prompt

> Event counts don't match items processed. Fix. Return the updated code.

## What the Code Does

A two-file batch processor. `processor.py` iterates over items (dicts with `id` and `value`), calling `increment()` and `emit_event()` from `metrics.py` for each item.

**processor.py:**
```python
def process_batch(items):
    for item in items:
        increment(item["value"])
    # BUG: emit_event moved outside loop -- only last item emitted
    emit_event(item["id"], item["value"])
    return len(items)
```

**metrics.py** defines `emit_event()` which appends an event dict to `_events` and `increment()` which accumulates a counter. Both are straightforward state-mutation functions.

The contract: for each item processed, exactly one event should be emitted with that item's `id`.

## The Bug

`emit_event()` is called once after the loop exits instead of once per iteration. It uses the loop variable `item`, which retains the value of the **last** item after the loop. Result: only 1 event is emitted (for the last item) instead of 3 events (one per item).

The bug is silent -- no exception is raised, and the function returns `len(items)` correctly. The mismatch is only visible by inspecting `_events`.

## The Correct Fix

Move `emit_event()` inside the loop:

```python
def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])  # moved inside loop
    return len(items)
```

**Lines changed:** 2 (move `emit_event` call into loop body, adjust indentation)

## What the Test Checks

1. Reset module state (`_counter = 0`, `_events = []`)
2. Call `process_batch([{"id": "a1", "value": 10}, {"id": "a2", "value": 20}, {"id": "a3", "value": 30}])`
3. **Assert:** `len(get_events()) == 3` -- one event per item
4. **Assert:** event IDs match `["a1", "a2", "a3"]` in order

## Why This Is Difficult for LLMs

- **Batching looks like optimization:** Emitting a single event after processing looks like an intentional design choice. The F2 ecological fallacy makes the batch-level call seem equivalent to per-item calls.
- **Cross-file reasoning required:** The model must understand that `emit_event()` (defined in `metrics.py`) appends to a list -- it is not idempotent or cumulative. Each call adds exactly one entry.
- **Loop variable leakage:** Python's scoping lets `item` survive after the loop, so `emit_event(item["id"], item["value"])` doesn't raise a NameError -- it silently uses the last item. Models may not flag this as suspicious.
- **Common wrong fix:** Adding deduplication or changing event structure instead of simply moving the call inside the loop.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about what would happen if `emit_event` were moved inside the loop (an intervention). Simply observing the code's current behavior (L1) shows "one event is emitted"; the fix requires reasoning counterfactually: "if this call were inside the loop, N events would be emitted."

### Trap Type: F2: Ecological fallacy (batch != per-item)

The ecological fallacy manifests as: "the batch processed 3 items and an event was emitted, so events are being tracked." The aggregate view (batch-level) obscures the per-item failure. The model must reason at the item granularity, not the batch granularity.

### Why This Case Is L2, Not L1 or L3

**Not L1** because understanding the bug requires tracing `emit_event()` across the file boundary to `metrics.py` to confirm it appends one entry per call (not a batch summary). The bug is in `processor.py` but the invariant depends on `metrics.py`'s behavior.

**Not L3** because there are only two files and one function boundary to trace. There is no multi-step state evolution or temporal ordering beyond "call happens inside vs. outside loop."

## Failure Mode Being Tested

**SIDE_EFFECT_ORDER** (hidden_dependency) -- a per-item side effect is incorrectly hoisted to batch level. The cross-file dependency between `processor.py` and `metrics.py` makes the single-call-per-item contract non-obvious.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace cross-file effect to identify the placement bug |
| 4o-mini | REI | May recognize the mismatch but produce incomplete fix |
| 5-mini | CSF | Should trace the cross-file dependency and fix placement |
