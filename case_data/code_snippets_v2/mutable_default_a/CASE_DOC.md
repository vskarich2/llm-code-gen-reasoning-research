# Case: mutable_default_a

**Family:** mutable_default
**Difficulty:** A (Easy)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F3 Confounding: default arg is hidden shared state

---

## Task Prompt

> Refactor this queue module for clarity. Return the updated code.

## What the Code Does

A single-file task queue module. Tasks are created as dicts with `name` and `priority` fields. The `enqueue` function adds a task to a queue and returns it. The `process` function processes all tasks in a queue.

### Files

**queue.py**
- `enqueue(task, queue=[])` -- adds task to queue and returns queue; default arg is a mutable list (BUG)
- `make_task(name, priority=1)` -- creates a task dict `{"name": name, "priority": priority}`
- `process(queue)` -- processes all tasks, returns list of result strings

## The Bug

Line 4: `def enqueue(task, queue=[])` uses a mutable default argument. In Python, default arguments are evaluated once at function definition time. The same list object is reused across all calls that don't provide an explicit `queue` argument. Tasks accumulate: the first call adds one task, the second call adds another task to the SAME list, resulting in a queue with two tasks when only one was intended.

The invariant violated: each call with a single task (no explicit queue) must return a list containing only that task.

## The Correct Fix

```python
def enqueue(task, queue=None):
    """Add a task to the queue and return the queue."""
    if queue is None:
        queue = []
    queue.append(task)
    return queue
```

2 lines changed (change default from `[]` to `None`, add `if queue is None: queue = []`).

## What the Test Checks

1. `make_task("alpha")` creates task 1
2. `make_task("beta")` creates task 2
3. `enqueue(t1)` returns queue 1
4. `enqueue(t2)` returns queue 2
5. `len(q2)` must be `1` (not `2` -- beta only, not alpha+beta)
6. `q2[0]["name"]` must be `"beta"`

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" without mentioning any bug. An LLM focused on cosmetic changes will leave the mutable default intact.
- `def f(items=[])` is one of the most well-known Python gotchas. However, it is precisely because it is "well-known" that an LLM might either (a) fix it automatically from pattern matching, or (b) assume the developer intended the accumulation behavior.
- The function works perfectly on the first call. The bug only manifests on the second and subsequent calls with no explicit queue argument.
- `process(queue)` works correctly, so the module appears functional if tested with only one enqueue call.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is associational: the model can observe `queue=[]` in the function signature and associate this with Python's mutable default argument behavior. The bug is recognizable from the syntax alone, without needing to trace execution across functions.

### Trap Type: F3: Confounding

The mutable default list `[]` is the hidden common cause (confounder). Each call to `enqueue` that relies on the default appears to create an independent queue, but all such calls secretly share the same list object. The confounding structure: the shared default list causally affects both call 1's return value and call 2's return value. Call 1 appears to be independent of call 2, but they are confounded by the shared mutable state.

### Why This Case Is L1, Not L2/L3

- L1 because the bug is identifiable from a single line (`queue=[]`) using basic Python knowledge. No cross-function reasoning is required.
- Not L2 because no intervention analysis or cross-file tracing is needed.
- Not L3 because no temporal reasoning or counterfactual simulation is required -- the pattern `def f(x=[])` is a known antipattern.

## Failure Mode Being Tested

Retry/state accumulation via mutable default argument. The default arg creates hidden persistent state that leaks between what should be independent function calls. This is the classic Python mutable default argument pitfall.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May not recognize the mutable default pattern; cosmetic refactoring only |
| 4o-mini | Heuristic | Likely recognizes def f(x=[]) as a known Python antipattern from training data |
| 5-mini | CSF | Should immediately identify and fix the mutable default argument |

*These are hypotheses, not measurements.*
