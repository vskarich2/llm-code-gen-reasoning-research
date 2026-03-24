# Case: temporal_drift_b

**Family:** temporal_drift
**Difficulty:** B (Medium)
**Bug Pattern:** implicit_schema
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F4: Reverse causation / Direction error

---

## Task Prompt

> Raw stats show normalized values instead of actual. Fix. Return the updated code.

## What the Code Does

A two-file metrics pipeline. `transforms.py` provides three functions: `compute_raw_stats()`, `normalize()`, and `summarize_for_display()`. `pipeline.py` orchestrates the flow.

**transforms.py:**
```python
def compute_raw_stats(data):
    """Must be called on original data before any transforms."""
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0}
    return {"raw_max": max(data), "raw_min": min(data), "raw_sum": sum(data)}

def normalize(data):
    """Normalize data to 0-1 range."""
    ...

def summarize_for_display(cleaned):
    """Returns display_max, display_min, display_mean -- NOT raw keys.
    Distractor: similar to compute_raw_stats but different contract."""
    ...
```

**pipeline.py:**
```python
def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)  # BUG: should be data, not cleaned
    display = summarize_for_display(cleaned)
    return {"raw_stats": raw_stats, "cleaned": cleaned, "display": display}
```

The contract: `raw_stats` must reflect original data. `summarize_for_display` returns different keys (`display_max`, etc.) and correctly operates on cleaned data.

## The Bug

Same core bug as temporal_drift_a: `compute_raw_stats()` is called on `cleaned` (normalized, 0-1 range) instead of `data` (original values). But now the function is defined in a different file (`transforms.py`), and a distractor function `summarize_for_display()` has a similar signature but different keys and a correct contract (it should operate on cleaned data).

The direction error means raw_stats returns normalized values (max=1.0, min=0.0) instead of actual values.

## The Correct Fix

Change the argument from `cleaned` to `data`:

```python
def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(data)  # fixed: use original data
    display = summarize_for_display(cleaned)
    return {"raw_stats": raw_stats, "cleaned": cleaned, "display": display}
```

**Lines changed:** 1 (change `cleaned` to `data` in the `compute_raw_stats` call)

## What the Test Checks

1. Call `pipeline([100, 200, 300, 400, 500])`
2. **Assert:** `raw_stats["raw_max"] == 500` (not 1.0)
3. **Assert:** `raw_stats["raw_min"] == 100` (not 0.0)
4. **Assert:** `raw_stats["raw_sum"] == 1500` (not ~2.5)

## Why This Is Difficult for LLMs

- **Distractor: `summarize_for_display()`** looks similar to `compute_raw_stats()` -- both take a data array and return summary statistics. But they have different contracts and different key names. A model might consolidate them or swap their arguments, breaking the pipeline.
- **Cross-file separation:** The docstring of `compute_raw_stats` in `transforms.py` says "Must be called on original data before any transforms," but the call site in `pipeline.py` uses `cleaned`. The model must read the docstring across the file boundary.
- **`quick_summary()` distractor:** A function in `pipeline.py` that only uses `summarize_for_display`, suggesting the display path is the important one. This may divert attention from the `raw_stats` bug.
- **Direction error (F4):** The code flows linearly: normalize -> raw_stats -> display. The temporal ordering looks natural (process, then summarize). The model must recognize that `raw_stats` should break this linear flow by operating on pre-transform data.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason: "If I change the argument of `compute_raw_stats` from `cleaned` to `data`, the returned stats will reflect original values instead of normalized values." This requires understanding the intervention's effect across the file boundary (the function is in `transforms.py`, the call is in `pipeline.py`).

### Trap Type: F4: Reverse causation / Direction error

The causal direction is reversed: raw stats should precede transformation in the data flow, but the code computes them after. The `summarize_for_display` distractor reinforces the wrong direction -- it correctly operates on cleaned data, making the pattern "compute stats on cleaned" look intentional.

### Why This Case Is L2, Not L1 or L3

**Not L1** because `compute_raw_stats` is defined in `transforms.py` and called from `pipeline.py`. The model must read the cross-file docstring to understand the contract.

**Not L3** because there is still only one transformation step and one stats computation, just split across two files. The distractor adds complexity but not additional state evolution steps.

## Failure Mode Being Tested

**TEMPORAL_DRIFT** (implicit_schema) -- a computation with an implicit contract (must operate on raw data) is called on post-transform data. The cross-file distractor makes the direction error harder to detect.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the cross-file contract with distractor |
| 4o-mini | REI | May identify the issue but confuse raw_stats with summarize_for_display |
| 5-mini | CSF | Should trace the contract across files and fix the argument |
