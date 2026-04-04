# Case: index_misalign_a

**Family:** index_misalign
**Difficulty:** A (Easy)
**Bug Pattern:** partial_state_update
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1: Selection (only some parallel structures updated)

---

## Task Prompt

> Refactor this report builder for clarity. Return the updated code.

## What the Code Does

A single-file report builder in `report.py` using parallel arrays:

```python
_labels = []
_values = []

def add_entry(label, value, position=None):
    if position is not None:
        _labels.insert(position, label)
        # BUG: values always appended instead of inserted at position
        _values.append(value)
    else:
        _labels.append(label)
        _values.append(value)
```

`get_entry(index)` returns `(_labels[index], _values[index])`. `get_all()` zips the two arrays together.

## The Bug

When `position` is specified, `_labels` is correctly inserted at the given index, but `_values` is always appended to the end. This causes the parallel arrays to become desynchronized: after an insert at position 0, the label is at index 0 but the corresponding value is at the last index.

For example, after `add_entry("a", 1)`, `add_entry("b", 2)`, `add_entry("c", 3, position=0)`:
- `_labels` = `["c", "a", "b"]` (c inserted at 0)
- `_values` = `[1, 2, 3]` (3 appended to end)
- `get_entry(0)` returns `("c", 1)` instead of `("c", 3)`

**Violated invariant:** Parallel arrays must stay aligned.

## The Correct Fix

Change `_values.append(value)` to `_values.insert(position, value)` on line 16 of `report.py`:

```python
_values.insert(position, value)  # FIX: insert at position instead of append
```

**Lines changed:** 1

## What the Test Checks

1. After adding "alpha"/10, "beta"/20, then "gamma"/30 at position 0:
   - `get_entry(0)` returns `("gamma", 30)`
2. `get_entry(1)` returns `("alpha", 10)` -- confirming full alignment

## Why This Is Difficult for LLMs

- **Refactor framing hides the bug:** The task says "refactor for clarity," not "fix a bug." A model focused on naming or structure may preserve the append.
- **append vs insert are both valid list operations:** The model must recognize that when `_labels` uses `insert`, `_values` must also use `insert` to maintain parallelism.
- **Bug only manifests with position argument:** When `position` is None (the else branch), both arrays use `append` and stay aligned. The bug is only visible when the optional `position` parameter is used.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible by reading the `add_entry` function: in the `if position is not None` branch, `_labels.insert(position, ...)` is paired with `_values.append(...)`. The asymmetry is directly observable without cross-function or cross-file reasoning.

### Trap Type: F1: Selection (only some parallel structures updated)

The `add_entry` function performs a selective update: it correctly uses `insert` for `_labels` but selects `append` for `_values`. Only one of the two parallel structures is updated consistently -- the other is treated differently, causing a selection-based misalignment.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-file or cross-function tracing is needed. Both arrays and the bug are in the same function.
- **Not L3:** No counterfactual or multi-step reasoning is required.

## Failure Mode Being Tested

**partial_state_update** -- Two parallel data structures that must stay synchronized are updated with different operations (insert vs append), causing them to silently drift apart.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May focus on cosmetic refactoring and preserve the append/insert asymmetry |
| 4o-mini | Heuristic | Likely to notice the asymmetry during refactoring |
| 5-mini | CSF | Should identify the insert/append mismatch through parallel structure analysis |
