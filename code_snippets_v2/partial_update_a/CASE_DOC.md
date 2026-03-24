# Case: partial_update_a

**Family:** partial_update
**Difficulty:** A (Easy)
**Bug Pattern:** partial_state_update
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1 Selection: only some fields updated

---

## Task Prompt

> Refactor this profile module for clarity. Return the updated code.

## What the Code Does

A single-file user profile module. Users are represented as dicts with `name`, `display_name`, `email`, and `age` fields. `create_user` initializes both `name` and `display_name` to the same value. `update_profile` applies changes from a dict but fails to keep `display_name` in sync when `name` changes.

### Files

**profile.py**
- `update_profile(user, changes)` -- iterates over changes dict and applies field updates; handles `name`, `email`, and `age` keys
- `create_user(name, email)` -- creates a user dict with `name`, `display_name` (set equal to `name`), `email`, and `age`

## The Bug

In `update_profile`, line 11: when `key == "name"`, only `user["name"]` is updated. The function does NOT update `user["display_name"]` to match. The docstring states the invariant: "display_name must always equal name." After `update_profile(user, {"name": "Bob"})`, `user["name"]` is `"Bob"` but `user["display_name"]` is still `"Alice"`.

The bug is silent -- no exception is raised. The inconsistency only manifests when downstream code reads `display_name` expecting it to match `name`.

## The Correct Fix

Add a line after `user["name"] = value` to sync display_name:

```python
if key == "name":
    user["name"] = value
    user["display_name"] = value  # ADD: keep display_name in sync
```

2 lines changed (1 added).

## What the Test Checks

1. `create_user("Alice", "alice@example.com")` creates a user
2. `update_profile(user, {"name": "Bob"})` updates the name
3. `user["name"]` must equal `"Bob"`
4. `user["display_name"]` must equal `"Bob"` (the critical assertion)

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" without mentioning any bug. An LLM focused on cosmetic refactoring will miss the missing sync.
- The `name` update branch has no visible error -- it does update `name` correctly. The omission of `display_name` is a missing line, not a wrong line.
- The implicit invariant (display_name == name) is stated only in the docstring. An LLM that ignores docstrings will miss it.
- The `create_user` function correctly sets both fields, so the invariant holds at creation time. The violation only occurs on update, requiring the model to reason about state consistency across operations.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is associational: the model can observe from `create_user` that `display_name` is set equal to `name`, and observe in `update_profile` that `name` is updated but `display_name` is not. The bug is visible from reading the code and noting the asymmetry.

### Trap Type: F1: Selection

The selection bias manifests as only some fields being updated. The `update_profile` function selects `name` for update but omits the dependent `display_name` field. The `last_name` and `email` branches don't have this problem (no dependent fields), so the partial update pattern is non-uniform -- making it easy to miss the one branch that is incomplete.

### Why This Case Is L1, Not L2/L3

- L1 because the bug is identifiable within a single function by comparing what `create_user` sets up (both fields synced) with what `update_profile` maintains (only name updated).
- Not L2 because no cross-function tracing or intervention reasoning is needed. The invariant and the violation are both visible in `profile.py`.
- Not L3 because no temporal sequence or counterfactual reasoning is required.

## Failure Mode Being Tested

Partial state update: a multi-field update operation misses a dependent field. This tests whether the model can identify that updating a primary field requires updating derived/dependent fields to maintain data consistency.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to do cosmetic refactoring only; will not notice the missing sync |
| 4o-mini | Heuristic | May notice the asymmetry between create_user and update_profile |
| 5-mini | CSF | Should recognize the display_name invariant from the docstring and code structure |

*These are hypotheses, not measurements.*
