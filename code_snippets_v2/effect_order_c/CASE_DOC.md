# Case: effect_order_c

**Family:** effect_order
**Difficulty:** C (Hard)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F2: Ecological fallacy (batch != per-item)

---

## Task Prompt

> Audit log has fewer entries than items. Fix. Return the updated code.

## What the Code Does

A three-file batch processor with coupled side effects per item: counter increment, event emission, and audit logging.

**processor.py:**
```python
def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
    # BUG: audit_log at batch level instead of per-item
    audit_log(item["id"], "processed", f"value={item['value']}")
    return len(items)
```

**metrics.py** provides `increment()` and `emit_event()` (correctly called inside the loop).

**audit.py** provides `audit_log()` which appends one audit entry per call to `_audit_log`.

A **distractor function** `fast_process()` in `processor.py` legitimately batches all three effects -- it is an optimized bulk path that intentionally uses a single audit entry. This makes the batch-level `audit_log` call in `process_batch` look intentional by analogy.

## The Bug

`audit_log()` is called once after the loop exits, not once per item inside the loop. For 3 items, only 1 audit entry is created instead of 3. The bug mirrors `effect_order_b` but with an added distractor: `fast_process()` demonstrates that batch-level auditing is sometimes correct, making it harder to identify that `process_batch` requires per-item auditing.

The loop variable `item` leaks from the for-loop, so the single audit entry records only the last item's data. No exception is raised.

## The Correct Fix

Move `audit_log()` inside the loop:

```python
def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
        audit_log(item["id"], "processed", f"value={item['value']}")  # moved inside loop
    return len(items)
```

**Lines changed:** 2 (move `audit_log` call into loop body, adjust indentation)

## What the Test Checks

1. Reset all module state (`_counter = 0`, `_events = []`, `_audit_log = []`)
2. Call `process_batch([{"id": "x1", "value": 5}, {"id": "x2", "value": 15}, {"id": "x3", "value": 25}])`
3. **Assert:** `len(get_audit_log()) == 3` -- one audit entry per item
4. **Assert:** audit entry IDs match `["x1", "x2", "x3"]` in order

## Why This Is Difficult for LLMs

- **Distractor function:** `fast_process()` in the same file legitimately uses batch-level auditing. It has a docstring saying "do not change." An LLM may use `fast_process` as a template and conclude that batch-level auditing is the intended pattern for `process_batch` too.
- **Three files to trace:** The model must understand the behavior of `audit_log()` from `audit.py`, `emit_event()` and `increment()` from `metrics.py`, and the two code paths in `processor.py`.
- **Partial correctness:** Two of the three effects (`increment` and `emit_event`) are already correctly placed inside the loop. Only `audit_log` is misplaced. The model must recognize that three effects should be symmetric but one is not.
- **Common wrong fixes:** (a) Modifying `fast_process` instead of `process_batch`, (b) adding deduplication to audit instead of fixing placement, (c) changing audit granularity globally.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through the loop in `process_batch`: trace that `increment` and `emit_event` are called per-item (inside the loop) while `audit_log` is called once (outside the loop). This is deterministic state tracing across modules -- the model verifies the mechanism by checking that `audit_log` appends one entry per call, then counts that only 1 entry is created for 3 items. The `fast_process` distractor requires distinguishing two code paths with different contracts, but this is multi-step causal propagation, not alternative-world reasoning.

### Trap Type: F2: Ecological fallacy (batch != per-item)

The ecological fallacy is reinforced by the `fast_process` distractor: if batch-level auditing is correct for one code path, it seems correct for all. The model must distinguish between the two processing modes and recognize that `process_batch` has a per-item contract while `fast_process` has a batch contract.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug requires understanding code across three files (processor, metrics, audit) to identify which effect is misplaced and why.

**L2 (deep)** because the model must trace three side effects through the loop, verify which are inside vs. outside, and distinguish the contracts of two code paths (`process_batch` vs. `fast_process`). This is multi-step causal propagation across three files with a distractor, but all reasoning is deterministic forward path analysis.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The loop structure, the call placement, and the side-effect counts are all directly observable from tracing the code.

## Failure Mode Being Tested

**SIDE_EFFECT_ORDER** (hidden_dependency) -- a per-item side effect is incorrectly batched, compounded by a legitimate batch-level distractor in the same file. Tests the model's ability to distinguish between two code paths with different effect granularity requirements.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot handle 3-file reasoning with distractor |
| 4o-mini | CSF | Likely confused by fast_process distractor |
| 5-mini | CSF | Distractor plus 3-file trace is near the boundary |
