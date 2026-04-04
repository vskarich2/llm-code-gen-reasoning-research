# Case: mutable_default_c

**Family:** mutable_default
**Difficulty:** C (Hard)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L2
**Pearl Level:** L2 Intervention (multi-hop state propagation tracing through decorator closure)
**Trap Type:** F3 Confounding: default arg is hidden shared state

---

## Task Prompt

> Scheduler history is shared across jobs. Fix. Return the updated code.

## What the Code Does

A three-file task scheduling system with a decorator that tracks call history. The queue module handles task creation. The worker module processes tasks. The scheduler module defines a `with_history` decorator that records call history for decorated functions, but uses a shared module-level list as the default history, causing all decorated functions to share the same history.

### Files

**queue.py**
- `create_task(name, priority=1)` -- creates a task dict
- `enqueue_all(tasks, queue=None)` -- enqueues multiple tasks (correctly uses `None` default)
- `drain(queue)` -- removes and returns all tasks from queue

**worker.py**
- `process(task)` -- processes a single task, returns result dict
- `batch_process(tasks)` -- processes a list of tasks

**scheduler.py**
- `_shared_log = []` -- module-level list (the hidden shared state)
- `with_history(func, history=_shared_log)` -- decorator that wraps `func` to record calls into `history`; default `history` param is the module-level `_shared_log` (BUG)
- `schedule_one(task)` -- decorated with `@with_history`; schedules and processes one task
- `schedule_batch(tasks)` -- decorated with `@with_history`; schedules and processes a batch
- `get_all_stats()` -- returns history lengths for both functions (distractor)

## The Bug

In `scheduler.py`, line 9: `def with_history(func, history=_shared_log)` uses `_shared_log` (a module-level mutable list) as the default for `history`. When `@with_history` is applied to both `schedule_one` and `schedule_batch`, neither call provides an explicit `history` argument, so both decorators receive the SAME list object (`_shared_log`). Every call to either function appends to the same list.

Result: calling `schedule_one` twice adds 2 entries to `_shared_log`. `schedule_batch.get_history()` then returns those same 2 entries even though `schedule_batch` was never called. The histories are not independent.

The invariant violated: each decorated function must have its own independent history list.

## The Correct Fix

In `scheduler.py`, change the decorator to create a new list for each decorated function:

```python
def with_history(func, history=None):
    """Decorator that records call history for a function."""
    if history is None:
        history = []

    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        history.append({"func": func.__name__, "args_count": len(args)})
        return result

    wrapper.get_history = lambda: list(history)
    wrapper.clear_history = lambda: history.clear()
    return wrapper
```

2 lines changed (change default from `_shared_log` to `None`, add `if history is None: history = []`).

## What the Test Checks

1. `schedule_one({"name": "solo_task", "priority": 1})` is called
2. `schedule_one({"name": "solo_task_2", "priority": 1})` is called
3. `schedule_one.get_history()` must have 2 entries
4. `schedule_batch.get_history()` must have 0 entries (never called, so its history must be empty)
5. If histories are shared, `schedule_batch.get_history()` would incorrectly have 2 entries

## Why This Is Difficult for LLMs

- The decorator closure pattern obscures the sharing. The `with_history` function is invoked at decoration time (via `@with_history`), and the default parameter binds then. The LLM must understand Python's decoration mechanism and default argument evaluation timing.
- `_shared_log = []` at module level looks like a reasonable module-level log. The fact that it is used as a default parameter in the decorator is the non-obvious connection.
- The `get_all_stats()` function actually reveals the bug (it reads both histories, which will be identical) but an LLM may not trace this through.
- `queue.py` correctly uses `None` default for `enqueue_all`, which might make the LLM think the codebase already handles mutable defaults. The bug is in a different module, in a different pattern (decorator default, not function default).
- An LLM might try to fix this by creating separate log lists for each function at module level, rather than using the cleaner `None` default pattern inside the decorator.
- The three-file structure adds cognitive load, though the worker and queue modules are distractors that work correctly.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention (Multi-Hop State Propagation Through Decorator Closure)

This requires L2 intervention reasoning: the model must trace how the `_shared_log` module-level list flows through the decorator's default parameter into the closure, and determine that the correct intervention is changing the default from `_shared_log` to `None` with a fresh list created inside the decorator body.

Each step in the chain is **deterministic**:
1. `_shared_log = []` at module level — a single list object
2. `def with_history(func, history=_shared_log)` — default parameter binds to that object at definition time
3. `@with_history` on `schedule_one` — no explicit `history` arg, so closure captures `_shared_log`
4. `@with_history` on `schedule_batch` — same: closure captures the SAME `_shared_log`
5. Calls to either function append to the same list

This is multi-hop state propagation tracing through Python's decoration mechanism — not counterfactual simulation. The model follows the reference chain: `_shared_log` → decorator default → closure → shared across functions. No alternative worlds need to be imagined; the model just needs to understand how Python evaluates default arguments at definition time and trace the resulting object identity.

The difficulty compared to Level B is the **indirection depth** (decorator + closure + module-level variable, vs. direct function default) and the fact that the sharing mechanism is less obvious (decorator closures vs. function signatures).

### Trap Type: F3: Confounding

The module-level `_shared_log` list is the hidden common cause confounding both decorated functions. `schedule_one` and `schedule_batch` appear to be independent functions with independent history tracking (each has its own `get_history` method). But they share state through `_shared_log`. The confounding is deeply hidden inside the decorator's closure mechanism: the sharing happens at decoration time (when `@with_history` evaluates the default parameter), not at call time.

### Why This Case Is L2, Not L1 or L3

- Not L1 because the bug requires understanding Python's decorator mechanism, default parameter evaluation timing, and closure semantics. No single line of code reveals the problem. The chain spans three files (scheduler.py defines the decorator, the decorated functions, and the module-level `_shared_log`).
- L2 because the model must trace multi-hop state propagation (module variable → decorator default → closure → shared state) and determine where to intervene. The intervention point (`history=None` inside `with_history`) requires understanding the full chain.
- **Not L3** because no counterfactual simulation is required. Each step is deterministic — the model traces how Python evaluates the default argument at definition time and follows the reference. The decoration-time vs. call-time distinction is about understanding Python's execution model, not about imagining alternative execution paths. The fix (`None` default pattern) is the same as Levels A and B, applied through a different mechanism.

## Failure Mode Being Tested

Retry/state accumulation via shared mutable default in a decorator. The decorator pattern obscures the mutable default issue because the sharing happens at decoration time through a closure, not at call time through a function parameter. This is a higher-order version of the classic `def f(x=[])` antipattern, where the default is bound in a decorator factory rather than a regular function.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Very unlikely to understand decorator closure semantics and shared default binding |
| 4o-mini | CSF | May recognize mutable default pattern but struggle with decorator-time binding |
| 5-mini | CSF | Best chance but decorator closures with shared defaults are challenging even for strong models |

*These are hypotheses, not measurements.*
