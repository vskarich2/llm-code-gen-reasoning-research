# Case: partial_update_b

**Family:** partial_update
**Difficulty:** B (Medium)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1 Selection: only some fields updated

---

## Task Prompt

> Users report their full name not updating. Fix the profile update. Return the updated code.

## What the Code Does

A two-file profile system with validation. Users have `first_name`, `last_name`, `full_name` (derived), and `email`. The validation module provides name validation and string sanitization. The profile module creates users and handles updates, but the update function has an asymmetric bug in how it handles `first_name` vs `last_name` changes.

### Files

**profile.py**
- `create_user(first_name, last_name, email)` -- creates user with derived `full_name = first_name + " " + last_name`
- `update_profile(user, changes)` -- iterates changes, validates and sanitizes values, updates fields; recomputes `full_name` for `last_name` changes but NOT for `first_name` changes

**validation.py**
- `validate_name(name)` -- returns True if name is a non-empty string
- `validate_email(email)` -- returns True if email contains '@'
- `sanitize_string(value)` -- strips whitespace from strings

## The Bug

In `profile.py`, lines 23-25: when `key == "first_name"`, `user["first_name"]` is updated but `user["full_name"]` is NOT recomputed. Compare with lines 26-28: when `key == "last_name"`, both `user["last_name"]` and `user["full_name"]` are updated. The invariant `full_name == first_name + ' ' + last_name` is violated when only `first_name` changes.

After `update_profile(user, {"first_name": "Bob"})` on a user created as `("Alice", "Smith", ...)`, `full_name` remains `"Alice Smith"` instead of becoming `"Bob Smith"`.

## The Correct Fix

In `profile.py`, after line 24 (`user["first_name"] = value`), add:

```python
if key == "first_name" and validate_name(value):
    user["first_name"] = value
    user["full_name"] = value + " " + user["last_name"]  # ADD: recompute full_name
```

2 lines changed (1 added).

## What the Test Checks

1. `create_user("Alice", "Smith", "alice@example.com")` creates a user
2. `update_profile(user, {"first_name": "Bob"})` updates first_name
3. `user["full_name"]` must equal `"Bob Smith"` (not stale `"Alice Smith"`)

## Why This Is Difficult for LLMs

- The trap: `validate_name()` in `validation.py` exists and runs during the update. An LLM might focus on the validation module, thinking the bug is a validation issue. The validation works correctly -- it is a distractor.
- The asymmetry is subtle: `last_name` correctly recomputes `full_name`, but `first_name` does not. An LLM scanning the code might see the `full_name` recomputation in the `last_name` branch and assume both branches handle it.
- The cross-file structure (profile.py imports from validation.py) may lead the LLM to look for bugs in validation.py instead of the missing line in profile.py.
- `sanitize_string()` is called on every value, adding another layer of processing that looks like it could be the source of problems.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about intervention: "If I add `full_name` recomputation to the `first_name` branch, will the symptom disappear?" This requires understanding the causal structure: `first_name` change -> should trigger `full_name` recomputation -> but the code lacks this causal link. The model must also reason about NOT intervening in validation.py (which works correctly).

### Trap Type: F1: Selection

Selection bias in field updates: the developer correctly implemented the `full_name` sync for `last_name` changes but missed it for `first_name` changes. This partial implementation creates a selection effect where only some update paths maintain the invariant. The model must notice which path is incomplete.

### Why This Case Is L2, Not L1/L3

- Not L1 because the task prompt points to a symptom ("full name not updating") that requires tracing across the update logic and understanding which branch is missing the recomputation. The validation module adds a cross-file dimension.
- L2 because the model must reason about which intervention (adding `full_name` sync to the `first_name` branch) will fix the causal chain, and distinguish this from irrelevant interventions (changing validation logic).
- Not L3 because the causal chain is single-step (one update call) and doesn't require temporal reasoning or counterfactual simulation across multiple events.

## Failure Mode Being Tested

Partial state update with hidden dependency: a derived field (`full_name`) depends on two primary fields (`first_name`, `last_name`), but the update logic only maintains the dependency for one of them. Tests whether the model can identify asymmetric field synchronization bugs.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May get confused by the validation module distractor |
| 4o-mini | REI | May focus on validation.py or only patch last_name logic |
| 5-mini | CSF | Should trace the asymmetry between first_name and last_name branches |

*These are hypotheses, not measurements.*
