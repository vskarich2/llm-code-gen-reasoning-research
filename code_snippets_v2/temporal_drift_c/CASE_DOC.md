# Case: temporal_drift_c

**Family:** temporal_drift
**Difficulty:** C (Hard)
**Bug Pattern:** implicit_schema
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F4: Reverse causation / Direction error

---

## Task Prompt

> Report shows wrong raw metrics. Fix the pipeline. Return the updated code.

## What the Code Does

A three-file, four-stage metrics pipeline.

**transforms.py** provides:
- `normalize(data)` -- normalize to 0-1 range
- `clip(data, lower, upper)` -- clip values to a range
- `scale(data, factor)` -- scale values by a factor
- `summarize_for_display(cleaned)` -- returns `display_max`, `display_min`, `display_mean` (NOT raw keys)

**metrics.py** provides:
- `compute_raw_stats(data)` -- returns `raw_max`, `raw_min`, `raw_sum`, `raw_count` (must be called on original data)
- `compute_derived(raw_stats)` -- computes `raw_mean` from raw stats

**pipeline.py** orchestrates the four stages:
```python
def pipeline(data):
    # Stage 2: normalize
    normalized = normalize(data)
    # Stage 3: clip
    clipped = clip(normalized, 0.05, 0.95)
    # Stage 1: raw stats -- MISPLACED
    raw_stats = compute_raw_stats(normalized)  # BUG: should be data, not normalized
    derived = compute_derived(raw_stats)
    # Stage 4: display summary
    display = summarize_for_display(clipped)
    return {
        "raw_stats": raw_stats, "derived": derived,
        "cleaned": clipped, "display": display,
    }
```

The stages are numbered in comments but executed out of order. Stage 1 (raw stats) is computed AFTER stages 2 and 3, and uses `normalized` instead of `data`.

## The Bug

`compute_raw_stats()` is called on `normalized` (post-normalization, 0-1 range) instead of `data` (original values). The stage ordering in the code contradicts the numbered comments: "Stage 1: raw stats" runs third. The raw stats contain normalized values: `raw_max` is 1.0 instead of the actual maximum.

Additionally, `compute_derived()` propagates the error -- `raw_mean` is computed from the wrong raw stats, creating a second-order effect.

## The Correct Fix

Change the argument from `normalized` to `data`:

```python
def pipeline(data):
    normalized = normalize(data)
    clipped = clip(normalized, 0.05, 0.95)
    raw_stats = compute_raw_stats(data)  # fixed: use original data
    derived = compute_derived(raw_stats)
    display = summarize_for_display(clipped)
    return {
        "raw_stats": raw_stats, "derived": derived,
        "cleaned": clipped, "display": display,
    }
```

**Lines changed:** 1 (change `normalized` to `data` in the `compute_raw_stats` call)

## What the Test Checks

1. Call `pipeline([15, 45, 90, 120, 60])`
2. **Assert:** `raw_stats["raw_max"] == 120` (not 1.0 from normalized)
3. **Assert:** `raw_stats["raw_min"] == 15` (not 0.0 from normalized)
4. **Assert:** `raw_stats["raw_sum"] == 330` (not ~2.57 from normalized)
5. **Assert:** `raw_stats["raw_count"] == 5`

## Why This Is Difficult for LLMs

- **Four stages with misordered comments:** The stage numbering (1-4) in comments does not match execution order. "Stage 1: raw stats" runs after stages 2 and 3. Models may trust the comments and not notice the execution order mismatch.
- **Three files to trace:** The model must understand `transforms.py` (normalize, clip, summarize_for_display), `metrics.py` (compute_raw_stats, compute_derived), and `pipeline.py` (orchestration).
- **Trap: consolidating `compute_raw_stats` and `summarize_for_display`.** They have similar signatures but different key names (`raw_*` vs `display_*`). Merging them breaks the API. The docstring in `transforms.py` explicitly warns about this.
- **`quick_report()` distractor:** A function in `pipeline.py` that uses only `normalize` and `summarize_for_display`, suggesting the display path is the "normal" one. This diverts attention from the raw stats bug.
- **Second-order error:** `compute_derived(raw_stats)` computes `raw_mean` from the wrong raw stats. Even if the model fixes `compute_raw_stats`, it might not realize `compute_derived` is automatically fixed too (it is, since it reads from `raw_stats`).
- **Direction error (F4) in a multi-stage pipeline:** With two transformation steps (normalize, clip) before the raw stats computation, the direction error is compounded. The model must recognize that raw stats should be computed before ANY transformation, not just before the last one.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through a four-stage pipeline: trace the data flow to see that `normalize(data)` transforms the original values, then `compute_raw_stats(normalized)` receives already-transformed data instead of the original `data`. This is deterministic state tracing across modules -- the model verifies the mechanism by checking what each function receives and returns, identifying that `compute_raw_stats` is called on the wrong variable. The second-order effect through `compute_derived` is also deterministic forward propagation.

### Trap Type: F4: Reverse causation / Direction error

The direction error is embedded in a multi-stage pipeline. Two transformations (normalize, clip) intervene between the raw data and the raw stats computation. The numbered comments suggest the "correct" stage order but the code executes them differently. The model must reason about which data version each function should receive.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the pipeline spans three files with four stages. No single-file analysis reveals the full data flow.

**L2 (deep)** because the model must trace data through multiple transformation stages across three files, verify the mechanism at each stage (normalize, clip, raw stats, derived), and identify which variable is passed to `compute_raw_stats`. The misordered stage comments, the distractor (`summarize_for_display`), and the second-order effect (`compute_derived`) add complexity, but all reasoning is multi-step causal propagation through deterministic code paths.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The variable names, function arguments, and transformation results are all directly observable from tracing the pipeline forward.

## Failure Mode Being Tested

**TEMPORAL_DRIFT** (implicit_schema) -- a computation with an implicit "must-run-on-raw-data" contract is placed after multiple transformations in a multi-stage pipeline. The three-file architecture, misordered stage comments, and consolidation trap make this the hardest case in the family.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace 4-stage pipeline across 3 files |
| 4o-mini | CSF | May identify the issue but confuse the multiple transformation stages |
| 5-mini | CSF | Multi-stage pipeline with distractors is near the capability boundary |
