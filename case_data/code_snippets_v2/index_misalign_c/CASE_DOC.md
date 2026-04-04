# Case: index_misalign_c

**Family:** index_misalign
**Difficulty:** C (Hard)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1: Selection (only some parallel structures updated)

---

## Task Prompt

> Report formatting breaks after inserting column. Fix. Return the updated code.

## What the Code Does

Three files implement a table report with formatting:

**`data.py`** provides `make_row(values, num_cols)` that pads/truncates a row to match column count, and `validate_table(headers, rows, widths)` that checks all three arrays have consistent lengths.

**`formatter.py`** provides `format_table(headers, rows, widths)` that uses `widths[i]` to pad each column with `ljust()`, and `recalculate_widths(headers, rows)` that computes optimal widths from actual data.

**`report.py`** contains a `Report` class with three parallel structures:

```python
class Report:
    def __init__(self, headers, default_width=10):
        self.headers = list(headers)
        self.rows = []
        self.column_widths = [default_width] * len(headers)

    def insert_column(self, position, header, default_value=""):
        self.headers.insert(position, header)
        for row in self.rows:
            row.insert(position, default_value)
        # BUG: column_widths not updated -- stays at old length
```

## The Bug

`insert_column()` correctly updates `self.headers` (insert at position) and `self.rows` (insert default_value at position in each row), but does NOT update `self.column_widths`. After inserting a column:
- `self.headers` has N+1 elements
- Each row has N+1 elements
- `self.column_widths` still has N elements

This causes `validate()` to fail (header/width count mismatch) and `render()` to crash with an IndexError when `format_table` tries to access `widths[N]`.

**Violated invariant:** Parallel arrays must stay aligned.

## The Correct Fix

Add `column_widths.insert()` to `insert_column` in `report.py` (line 30):

```python
self.column_widths.insert(position, len(header))  # FIX: also insert into column_widths
```

**Lines changed:** 1

## What the Test Checks

1. Create a Report with headers ["name", "score"] and two rows
2. Insert column at position 1 with header "grade" and default value "A"
3. `validate()` returns `(True, "ok")` -- all three structures are in sync
4. `render()` does not crash -- widths array matches header count

## Why This Is Difficult for LLMs

- **Trap: `recalculate_widths` exists but is not called.** The `formatter.py` module provides `recalculate_widths(headers, rows)` which could be used to fix the widths. A model might call this function instead of directly inserting into `column_widths`. While calling `recalculate_widths` could work, the minimal fix is a single insert.
- **Three parallel structures:** The model must track headers, rows, AND column_widths simultaneously. The first two are correctly updated, creating a false sense of completeness.
- **Cross-file error manifestation:** The bug is in `report.py`'s `insert_column`, but the crash happens in `formatter.py`'s `format_table` when it accesses `widths[i]` beyond the array length.
- **Two out of three is almost right:** Headers and rows are correctly updated. The model may check those two, see they match, and conclude the function is correct without checking the third structure.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through `insert_column` and its downstream effects:
1. Tracing `insert_column` to see that headers and rows are updated but widths are not -- deterministic state tracing
2. Tracing `render()` into `format_table()` in `formatter.py` to see that it requires `widths` to match `headers` -- mechanism verification
3. Understanding that `validate_table()` in `data.py` checks the header/width alignment -- forward path analysis
4. Recognizing that `recalculate_widths` exists as a potential fix mechanism but isn't called

This is multi-step causal propagation across three files tracking three parallel structures through deterministic code paths.

### Trap Type: F1: Selection (only some parallel structures updated)

`insert_column` selectively updates two of three parallel structures (headers and rows) but not the third (column_widths). The selection is 2/3 complete -- close enough to look correct on cursory inspection, but the missing third structure causes downstream failures.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug requires understanding three parallel structures across three files.
- **L2 (deep):** The model must trace the cascade: insert_column -> render -> format_table -> IndexError, tracking three parallel structures (headers, rows, widths) and verifying the mechanism at each step. It must also consider whether `recalculate_widths` or `validate_table` provide alternative fix paths. This is multi-step causal propagation crossing multiple module boundaries.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The array lengths, the insert operations, and the IndexError are all directly observable from tracing the actual execution forward.

## Failure Mode Being Tested

**partial_state_update** -- A mutation operation updates two of three parallel structures, leaving the third stale. The error manifests as a crash in a different module that consumes the inconsistent state.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot track three parallel structures across three files |
| 4o-mini | CSF | May notice headers/rows are updated and stop checking, missing column_widths |
| 5-mini | CSF | Best chance but may be distracted by recalculate_widths as an alternative fix |
