# Case: l3_state_pipeline

**Family:** State/Semantic Violation
**Difficulty:** Hard (V1)
**Bug Pattern:** STATE_SEMANTIC_VIOLATION
**Causal Depth:** L3 (the ONLY true L3 case in V1)
**Pearl Level:** L3 Counterfactual (but-for causal necessity)
**Trap Type:** F1 Survivorship + F3 Confounding: remove commit() or merge stage+commit, losing frozen gate or breaking preview

---

## Task Prompt

> process_batch and process_incremental have redundant steps. stage() and commit() both copy data into the state, and freeze_view() rebuilds the view that stage() already built. Simplify the pipeline by removing the unnecessary steps. Return the updated code.

## What the Code Does

The system implements a data pipeline with five modules:

- **state.py** creates state dicts with fields: `raw`, `pending`, `stable`, `view`, `meta` (containing `version` and `frozen`).

- **reducers.py** provides the core transformations:
  - `stage(st, processed)` -- copies processed data into `pending`, builds `view` from it, increments version.
  - `commit(st)` -- copies `pending` to `stable`, sets `meta["frozen"] = True`.
  - `freeze_view(st)` -- rebuilds `view` from `stable` (not `pending`).

- **selectors.py** provides queries:
  - `get_committed_total(st)` -- returns `None` if `meta["frozen"]` is `False`; otherwise sums `stable` values.

- **pipeline.py** orchestrates the sequence:
  ```python
  def process_batch(entries):
      st = make_state(entries)
      cleaned = normalize(st["raw"])
      merged = collapse(cleaned)
      stage(st, merged)       # pending = merged, view = project(merged)
      commit(st)              # stable = pending, frozen = True
      freeze_view(st)         # view = project(stable)
      out = materialize(st)
      return st, out
  ```

- **api.py** uses the pipeline:
  - `ingest(entries)` calls `process_batch` then `get_committed_total`.
  - `preview(entries)` calls `stage` WITHOUT `commit` -- intentionally shows uncommitted data.

## The Bug

The buggy version (`pipeline_buggy.py`) removes both `commit()` and `freeze_view()` as "redundant":

```python
def process_batch(entries):
    ...
    stage(st, merged)
    # commit and freeze_view removed as redundant
    out = materialize(st)
    return st, out
```

This causes two failures:
1. `meta["frozen"]` remains `False`, so `get_committed_total(st)` returns `None` instead of the sum.
2. `stable` remains empty, so `materialize(st)["items"]` is `[]`.

## The Correct Fix

The reference fix (`reference_fixes/l3_state_pipeline.py`) preserves all three steps in their original order:

```python
stage(st, merged)       # Must exist: sets pending, builds initial view
commit(st)              # Must exist: copies pending->stable, sets frozen=True
freeze_view(st)         # Must exist: rebuilds view from stable (committed) data
```

Each step is causally necessary:
- **stage** is needed by `preview()` which calls `stage` without `commit`.
- **commit** sets the `frozen` gate that `get_committed_total` checks.
- **freeze_view** ensures `view` reflects `stable` (committed) state, not `pending`.

## What the Test Checks

1. Calls `process_batch([{"id": "a", "val": 10}, {"id": "b", "val": 20}])`.
2. Checks `st["meta"]["frozen"] == True` -- verifies `commit()` ran.
3. Checks `st["stable"]` is non-empty -- verifies `commit()` copied pending to stable.
4. Checks `get_committed_total(st) == 30` -- verifies both the frozen gate and the stable data are correct.

If `commit()` is removed, the frozen check fails and `get_committed_total` returns `None`.

## Why This Is Difficult for LLMs

1. **Surface redundancy is compelling:** After `stage()`, `pending` has the data and `view` has the projection. After `commit()`, `stable` gets the same data. After `freeze_view()`, `view` gets the same projection (since `stable == pending`). On the happy path, `commit` and `freeze_view` appear to duplicate what `stage` already did.

2. **The task prompt reinforces the trap:** It explicitly says "stage() and commit() both copy data" and "freeze_view() rebuilds the view that stage() already built." These are accurate descriptions of the surface behavior but ignore the semantic differences (frozen gate, stable vs pending distinction).

3. **Three-way interdependency:** Understanding why each step is necessary requires reasoning about three different downstream consumers: `get_committed_total` needs `frozen=True`, `materialize` needs `stable` data, and `preview` needs `stage` to work independently of `commit`.

4. **Counterfactual reasoning required:** The model must reason: "But for `commit()`, what would `get_committed_total` return?" This is genuinely L3 counterfactual: each step's necessity is established by reasoning about what breaks in its absence.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L3 Counterfactual (But-For Causal Necessity)

This is the only true L3 case in V1. The reasoning required is:

1. **But for `commit()`:** `meta["frozen"]` stays `False`, so `get_committed_total()` returns `None`. `stable` stays empty, so `materialize()` returns no items.
2. **But for `freeze_view()`:** `view` reflects `pending` state (from `stage`), not `stable` state (from `commit`). In the normal path these are identical, but the semantic contract requires the view to reflect committed data.
3. **But for keeping `stage` separate from `commit`:** `preview()` in `api.py` calls `stage` without `commit` intentionally. Merging them breaks the preview-without-commit pattern.

Each step's causal necessity is established only by reasoning about its absence -- the definition of counterfactual causation.

### Trap Type: F1 Survivorship + F3 Confounding

**F1 (Survivorship):** The model observes the happy path where `stage`, `commit`, and `freeze_view` produce the same data and concludes the later steps are redundant. It doesn't "see" the failure case (frozen gate returning None) because it only traces the success path.

**F3 (Confounding):** The task prompt conflates "copies data into state" (what stage and commit both do) with "has the same purpose." The confound is that the operations look similar at the data level but serve different semantic roles (pending vs committed, unfrozen vs frozen).

### Why This Case Is L3, Not L1 or L2

- **Not L1 (shallow):** The bug requires understanding the interaction between three functions across four files.
- **Not L2 (intervention only):** Pure intervention reasoning ("if I remove commit, trace forward") is necessary but not sufficient. The model must also reason about WHY each step exists -- its unique causal role. This requires counterfactual reasoning: "In a world without commit, does the system still work?" for each of the three steps independently.
- **L3 (counterfactual):** The but-for test is the definitive tool: each of `stage`, `commit`, and `freeze_view` is causally necessary because removing any one breaks a specific downstream consumer. This is counterfactual causation -- the cause is necessary for the effect.

## Failure Mode Being Tested

STATE_SEMANTIC_VIOLATION -- Removing `commit()` violates the state machine semantics: the `frozen` gate is never set, `stable` is never populated, and downstream selectors that depend on committed state return incorrect results.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot reason about multi-step state transitions; will remove "redundant" steps as the prompt suggests |
| 4o-mini | CSF | Likely removes commit and/or freeze_view based on the prompt's framing of redundancy |
| 5-mini | CSF | May partially understand the frozen gate but unlikely to preserve all three steps when the prompt says they are unnecessary |
