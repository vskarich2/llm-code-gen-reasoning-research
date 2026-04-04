# Case: index_misalign_b

**Family:** index_misalign
**Difficulty:** B (Medium)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1: Selection (only some parallel structures updated)

---

## Task Prompt

> Report columns are misaligned after deletion. Fix. Return the updated code.

## What the Code Does

Two files implement a tabular report system:

**`data.py`** provides `make_row(*values)` which converts positional values to a list, and `validate_row(row, expected_cols)` for validation.

**`report.py`** contains a `Report` class:

```python
class Report:
    def __init__(self, headers):
        self.headers = list(headers)
        self.rows = []

    def delete_column(self, index):
        # BUG: removes header but does NOT remove from rows
        del self.headers[index]

    def render(self):
        result = []
        for row in self.rows:
            result.append(dict(zip(self.headers, row)))
        return result
```

`render()` uses `zip(self.headers, row)` to create dicts. If headers and rows have different column counts, the zip produces incorrect key-value pairings.

## The Bug

`delete_column(index)` removes the header at `index` but does not remove the corresponding element from each row. After deleting column 1 ("age") from a 3-column table:
- `self.headers` = `["name", "city"]` (2 elements)
- `self.rows[0]` = `["Alice", 30, "NYC"]` (still 3 elements)
- `render()` zips: `{"name": "Alice", "city": 30}` -- "city" maps to 30 (the age value), not "NYC"

**Violated invariant:** Parallel arrays must stay aligned.

## The Correct Fix

Add row-element deletion to `delete_column` in `report.py` (after line 24):

```python
def delete_column(self, index):
    del self.headers[index]
    # FIX: also remove from each row
    for row in self.rows:
        del row[index]
```

**Lines changed:** 1 (add the for-loop with del)

## What the Test Checks

1. Create a Report with headers ["name", "age", "city"] and two rows
2. Delete column 1 ("age")
3. `render()` first row has `"name"` = `"Alice"` (not shifted)
4. `render()` first row has `"city"` = `"NYC"` (not the age value 30)

## Why This Is Difficult for LLMs

- **Trap: render looks correct in isolation.** The `render()` method correctly uses `zip(self.headers, row)` -- it has no bug itself. The bug is in `delete_column` which leaves the data in an inconsistent state.
- **Cross-function reasoning required:** The model must understand that `delete_column`'s incomplete update will cause `render()` to produce wrong results. This requires tracing the data flow from mutation to consumption.
- **zip masks the error:** Python's `zip` silently truncates to the shorter iterable, so no IndexError is raised. The misalignment produces wrong data, not a crash.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens if I call delete_column(1) and then render()?" This requires:
1. Understanding that `delete_column` only modifies `headers`
2. Tracing the stale rows through `render()`
3. Recognizing that `zip` will pair misaligned elements

This is a cross-function intervention where the mutation in one method affects the output of another.

### Trap Type: F1: Selection (only some parallel structures updated)

`delete_column` selectively updates `self.headers` but not `self.rows`. The selection is incomplete: only one of the two parallel structures is modified, leaving the other stale and causing misalignment.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug requires reasoning across two methods (`delete_column` and `render`) and understanding how the incomplete update in one causes wrong output in the other.
- **Not L3:** No counterfactual chain across multiple files or multi-step temporal reasoning is needed. The intervention is a straightforward two-step trace: delete -> render.

## Failure Mode Being Tested

**partial_state_update** -- A mutation operation updates one parallel structure (headers) but not the other (rows), causing them to silently drift apart. The consumer (`render`) produces wrong results without raising an error.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not trace from delete_column to render to see the misalignment |
| 4o-mini | REI | May focus on render() (which looks correct) rather than delete_column |
| 5-mini | CSF | Should trace the data flow and identify the missing row update |
