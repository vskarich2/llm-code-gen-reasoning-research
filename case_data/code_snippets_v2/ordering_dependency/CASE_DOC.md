# Case: ordering_dependency

**Family:** concurrency
**Difficulty:** medium
**Bug Pattern:** process runs before initialization
**Causal Depth:** 2
**Pearl Level:** L2
**Trap Type:** F6: lock doesn't fix ordering

---

## Task Prompt

> Fix the pipeline so that all items are processed regardless of whether they arrive before or after initialization.

## What the Code Does

`pipeline.py` implements a processing pipeline with three operations: `init()`, `process(item)`, and `shutdown()`. The pipeline uses a global `_initialized` flag and a `_log` list.

```python
def process(item):
    if not _initialized:
        _log.append(f"error:not_init:{item}")
        return False
    _log.append(f"processed:{item}")
    return True
```

Two scenario functions demonstrate the issue:
- `correct_order()`: init, process("a"), process("b"), shutdown -- all items processed correctly.
- `broken_order()`: process("a"), init, process("b"), shutdown -- item "a" arrives before init, is logged as an error and lost.

## The Bug

In `broken_order()`, `process("a")` runs before `init()`. Since `_initialized` is `False`, the item is logged as `"error:not_init:a"` and `False` is returned. The item is permanently lost -- there is no retry or buffering mechanism. After `init()` runs, only `process("b")` succeeds. The final log is `["error:not_init:a", "init", "processed:b", "shutdown"]`, with only 1 of 2 items processed.

The violated invariant: all items must be processed regardless of arrival order.

## The Correct Fix

The reference fix (`reference_fixes/ordering_dependency.py`) adds a buffer for pre-init items and drains it when init runs:

```python
def init():
    global _initialized
    _initialized = True
    _log.append("init")
    # FIX: drain buffer of any items that arrived before init
    for item in _buffer:
        _log.append(f"processed:{item}")
    _buffer.clear()

def process(item):
    """FIX: if not initialized, buffer the item for later processing."""
    if not _initialized:
        _buffer.append(item)
        return True  # buffered, not lost
    _log.append(f"processed:{item}")
    return True
```

Items arriving before init are buffered. When `init()` runs, it drains the buffer, processing all deferred items. The `broken_order()` log becomes `["init", "processed:a", "processed:b", "shutdown"]`.

## What the Test Checks

1. `correct_order()` must produce exactly `["init", "processed:a", "processed:b", "shutdown"]` with no errors.
2. `broken_order()` must produce exactly 2 processed items (entries starting with `"processed:"`).
3. `broken_order()` must contain no error entries.

## Why This Is Difficult for LLMs

- **F6 trap: a lock does not fix ordering.** A model might add a lock or synchronization primitive, but the problem is not mutual exclusion -- it is that items arrive before the system is ready. No amount of locking prevents `process` from being called before `init`.
- **Common wrong fix: auto-calling init inside process.** This changes the semantics -- `init` should only run once at the correct time, not be triggered by item arrival. The test expects `init` to appear in the log at a specific position.
- **Common wrong fix: reordering steps in `broken_order`.** This changes the test scenario rather than fixing the code to be robust.
- **The fix requires two coordinated changes:** `process` must buffer instead of error, AND `init` must drain the buffer. Missing either half produces incorrect behavior.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention

The model must reason: "If I intervene by adding a buffer in `process` and a drain in `init`, then items arriving before initialization will be deferred and eventually processed." This is a two-site intervention that requires understanding the temporal dependency between init and process.

### Trap Type: F6: lock doesn't fix ordering

The core issue is ordering, not exclusion. Even with perfect mutual exclusion, if `process("a")` runs before `init()`, the item is lost under the original code. The fix requires a fundamentally different approach: buffering and deferred processing. Models trained on concurrency patterns may reflexively reach for locks or barriers, which do not address the actual problem.

### Why This Case Is L2, Not L1 or L3

- **Not L1:** L1 would be recognizing "calling process before init is wrong." The model must design a buffering mechanism, not just identify the ordering violation.
- **Not L3:** L3 requires structural vs. contingent causation or but-for reasoning across multiple independent causes. Here the cause is singular (items lost when arriving pre-init) and the fix, while requiring changes in two functions, is a single coherent intervention (buffer-then-drain pattern).

## Failure Mode Being Tested

Ordering dependency: an operation fails silently when executed before a prerequisite has established necessary state.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely tries locks, auto-init, or reorders the test steps. Unlikely to implement buffer-drain pattern. |
| 4o-mini | partial | May implement buffering in `process` but forget to drain the buffer in `init`, or vice versa. |
| 5-mini | pass | Should recognize the need for both buffering and draining, producing a correct two-site fix. |
