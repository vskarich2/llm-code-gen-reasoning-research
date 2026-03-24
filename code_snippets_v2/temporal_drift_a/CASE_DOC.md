# Case: temporal_drift_a

**Family:** temporal_drift
**Difficulty:** A (Easy)
**Bug Pattern:** implicit_schema
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F4: Reverse causation / Direction error

---

## Task Prompt

> Refactor this metrics pipeline for clarity. Return the updated code.

## What the Code Does

A single-file metrics pipeline (`pipeline.py`) that computes raw statistics on input data and then normalizes the data.

```python
def compute_raw_stats(data):
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0}
    return {
        "raw_max": max(data),
        "raw_min": min(data),
        "raw_sum": sum(data),
    }

def normalize(data):
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi == lo:
        return [0.5] * len(data)
    return [(x - lo) / (hi - lo) for x in data]

def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)  # BUG: should be data, not cleaned
    return {"raw_stats": raw_stats, "cleaned": cleaned}
```

The contract: `raw_stats` must reflect the ORIGINAL input data, not the normalized version. The function name `compute_raw_stats` implies it operates on raw data.

## The Bug

`compute_raw_stats()` is called on `cleaned` (the normalized data, range 0-1) instead of `data` (the original input). After normalization, `raw_max` is always 1.0, `raw_min` is always 0.0, and `raw_sum` is the sum of normalized values -- none of which reflect the original data.

The ordering is backwards: normalize runs first, then raw stats are computed on the already-transformed data. This is a temporal ordering error -- the computation that must run on raw data was placed after the transformation.

## The Correct Fix

Swap the argument from `cleaned` to `data`:

```python
def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(data)  # fixed: use original data
    return {"raw_stats": raw_stats, "cleaned": cleaned}
```

Or equivalently, move `compute_raw_stats` before `normalize`:

```python
def pipeline(data):
    raw_stats = compute_raw_stats(data)
    cleaned = normalize(data)
    return {"raw_stats": raw_stats, "cleaned": cleaned}
```

**Lines changed:** 1 (change `cleaned` to `data` in the `compute_raw_stats` call)

## What the Test Checks

1. Call `pipeline([10, 50, 30, 80, 20])`
2. **Assert:** `raw_stats["raw_max"] == 80` (not 1.0 from normalized data)
3. **Assert:** `raw_stats["raw_min"] == 10` (not 0.0 from normalized data)
4. **Assert:** `raw_stats["raw_sum"] == 190` (not ~2.57 from normalized data)

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model may reorganize the pipeline without noticing the argument error.
- **The code runs without errors.** `compute_raw_stats(cleaned)` produces valid output -- just with wrong values (0.0 to 1.0 range instead of original values).
- **Direction error (F4):** The causal direction is reversed. The code implies "normalize data, then compute stats on the result." But the correct direction is "compute stats on raw data, then normalize." The function name `compute_raw_stats` hints at the correct argument, but the actual call uses the wrong variable.
- **`format_report()` distractor:** A helper function that formats the stats for display. It is unrelated to the bug but may draw attention.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible in one function (`pipeline`). The variable name `cleaned` (post-normalization) vs. `data` (original), combined with the function name `compute_raw_stats`, creates a pattern mismatch that can be detected through local association.

### Trap Type: F4: Reverse causation / Direction error

The temporal/causal direction is wrong. Raw stats should be computed BEFORE transformation, but the code computes them AFTER. This is a direction error: the model must recognize that the arrow goes from raw data -> stats, not from transformed data -> stats.

### Why This Case Is L1, Not L2 or L3

**Not L2** because `compute_raw_stats` and `normalize` are both defined in the same file. The pipeline function that contains the bug is self-contained -- no cross-file reasoning needed.

**Not L3** because there is a single transformation step and a single stats computation. No multi-step state evolution or multiple interacting pipelines.

## Failure Mode Being Tested

**TEMPORAL_DRIFT** (implicit_schema) -- a computation that must run on raw data is placed after a transformation, causing it to operate on the wrong version of the data. The implicit schema (raw_stats contract) is violated silently.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May recognize the naming mismatch but fail to change the argument |
| 4o-mini | Heuristic | Likely to notice raw_stats should use raw data |
| 5-mini | CSF | Should identify the argument error from naming alone |
