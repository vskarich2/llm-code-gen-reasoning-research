# Case: mutable_default_b

**Family:** mutable_default
**Difficulty:** B (Medium)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L1-L2 boundary
**Pearl Level:** L1-L2 Boundary (deterministic state tracing of known antipattern)
**Trap Type:** F3 Confounding: default arg is hidden shared state

---

## Task Prompt

> Workers skip valid tasks on second batch. Fix. Return the updated code.

## What the Code Does

A two-file task processing system. The queue module handles task creation and enqueueing (correctly, with `None` default). The worker module processes batches with deduplication, but the dedup `seen` set uses a mutable default argument that persists across calls.

### Files

**queue.py**
- `create_task(name, priority=1)` -- creates a task dict with `status: "pending"`
- `enqueue(task, queue=None)` -- correctly uses `None` default + creates list inside function
- `dequeue(queue)` -- removes and returns first task

**worker.py**
- `process_batch(tasks, seen=set())` -- processes tasks, skipping those whose name is in `seen`; BUG: default `set()` persists across calls
- `summarize(results)` -- formats result count (distractor)

## The Bug

In `worker.py`, line 6: `def process_batch(tasks, seen=set())` uses a mutable default argument. The `seen` set persists across calls. On the first call, task names are added to `seen`. On the second call, any task with a name that appeared in the first batch is skipped as a "duplicate" even though it is a legitimate task in a new, independent batch.

Example: batch 1 has `["task_x", "task_y"]`. Batch 2 has `["task_x", "task_z"]`. After processing batch 1, `seen = {"task_x", "task_y"}`. When batch 2 is processed, `task_x` is in `seen` and gets skipped, even though it is a valid task in a new batch.

The invariant violated: each call to `process_batch` with a fresh batch must process ALL tasks in that batch.

## The Correct Fix

```python
def process_batch(tasks, seen=None):
    """Process a batch of tasks, skipping already-seen ones."""
    if seen is None:
        seen = set()
    results = []
    for task in tasks:
        ...
```

2 lines changed (change default from `set()` to `None`, add `if seen is None: seen = set()`).

## What the Test Checks

1. `batch1 = [{"name": "task_x"}, {"name": "task_y"}]` -- first batch
2. `batch2 = [{"name": "task_x"}, {"name": "task_z"}]` -- second batch (task_x repeated intentionally)
3. `process_batch(batch1)` processes both tasks
4. `process_batch(batch2)` must process BOTH tasks (including task_x)
5. `r2` must have names `["task_x", "task_z"]` (not just `["task_z"]`)
6. `len(r2)` must be `2`

## Why This Is Difficult for LLMs

- The trap: the `seen` set looks like an intentional deduplication optimization. An LLM might believe the persistence across calls is desired behavior (dedup across batches). The task prompt ("workers skip valid tasks") hints otherwise, but the code structure suggests dedup is a feature.
- The bug is in `worker.py` but `queue.py` is also present. The queue module correctly uses `None` default, which might make the LLM think the codebase already handles mutable defaults correctly.
- `set()` as a mutable default is less commonly discussed than `[]`. An LLM might not recognize `set()` as having the same pitfall as `[]`.
- An LLM might try to fix the `seen` set by clearing it at the end of the function, but this would break intentional intra-batch dedup. The correct fix is the `None` default pattern.

## Causal Reasoning Required (L1-L2 Boundary)

### Pearl Level: L1-L2 Boundary (Deterministic State Tracing)

This case sits at the L1-L2 boundary. The mutable default `set()` antipattern is the same class of bug as Level A's `queue=[]` — a well-known Python gotcha. The model must trace that `seen=set()` persists across calls, causing inter-batch state leaking. This is **deterministic state tracing**: follow the object identity of the default argument across two calls to the same function.

The difficulty increase from Level A is in **locating** the bug across two files (queue.py correctly uses `None`, worker.py doesn't) and **distinguishing** intentional intra-batch dedup from accidental inter-batch leaking. But the underlying reasoning is the same as Level A: recognize the mutable default, apply the `None` default pattern.

### Trap Type: F3: Confounding

The mutable default `set()` is the hidden confounder. Batch 1 and batch 2 appear to be processed independently (separate `process_batch` calls), but they share state through the `seen` set. The confounding is more subtle than in Level A because the `seen` set's purpose (deduplication) makes the sharing look intentional. The confounder masquerades as a feature.

### Why This Case Is L1-L2 Boundary, Not L1 or Full L2

- Not pure L1 because the bug requires cross-file awareness (queue.py correctly uses `None` default, but worker.py doesn't) and understanding the semantic difference between intra-batch dedup (correct) and inter-batch state leaking (bug).
- Not full L2 (Intervention) because no causal graph reasoning is required. The model traces a deterministic behavior of Python's default argument evaluation — the same pattern as Level A, just harder to find across two files.
- Not L3 because the chain is two calls to the same function, not a multi-module state evolution.

## Failure Mode Being Tested

Retry/state accumulation via mutable default argument, but disguised as a deduplication feature. The `seen` set serves a legitimate purpose within a single call but its persistence across calls is a bug. This tests whether the model can distinguish between intended state retention and accidental state leaking.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not recognize set() as a mutable default issue |
| 4o-mini | REI | May think the seen set persistence is intentional dedup behavior |
| 5-mini | CSF | Should recognize the mutable default pattern and apply the None default fix |

*These are hypotheses, not measurements.*
