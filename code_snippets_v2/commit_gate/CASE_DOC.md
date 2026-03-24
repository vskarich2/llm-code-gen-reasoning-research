# Case: commit_gate

**Family:** state management / pipeline integrity
**Difficulty:** hard
**Bug Pattern:** two absent steps each independently necessary (but-for causal necessity)
**Causal Depth:** 3
**Pearl Level:** L3
**Trap Type:** Two absent steps each independently necessary

---

## Task Prompt

> Fix the pipeline so that ingest produces a non-null committed total, the view is consistent with committed data, and preview does not freeze state.

## What the Code Does

The case spans five files implementing a data pipeline:

**`state.py`** -- creates initial state with `raw`, `pending`, `stable`, `view`, and `meta` (version, frozen) fields.

**`reducers.py`** -- core operations:
- `normalize(raw)`: copies entries as dicts
- `collapse(entries)`: deduplicates by `id`
- `stage(st, data)`: sets `pending` and `view` to `data`, increments version
- `commit(st)`: promotes `pending` to `stable` (sorted by id), sets `frozen = True`
- `freeze_view(st)`: rebuilds `view` from `stable`
- `materialize(st)`: returns `view` as a list

**`selectors.py`** -- query functions:
- `get_committed_total(st)`: returns sum of `val` fields from `stable` only if `frozen` is `True`, else `None`
- `get_view_digest(st)`: order-sensitive `"|"` join of `id` fields from `view`
- `get_committed_digest(st)`: same but from `stable`, returns `None` if not frozen

**`pipeline.py`** -- the buggy file:
```python
def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    # commit(st)       -- removed as "redundant"
    # freeze_view(st)  -- removed as "redundant"
    return st, materialize(st)
```

**`api.py`** -- three entry points: `ingest`, `preview`, and `ingest_and_verify`.

## The Bug

Two lines are commented out in `pipeline.py`:

1. **Missing `commit(st)`**: Without commit, `stable` remains empty and `frozen` remains `False`. `get_committed_total` returns `None`. The `ingest` function reports `total: None`.

2. **Missing `freeze_view(st)`**: Without freeze_view, `view` contains the unsorted output of `stage` (which preserves input order). But `stable` (after commit) is sorted by `id`. So `get_view_digest` and `get_committed_digest` differ, causing `ingest_and_verify` to report `consistent: False`.

Each missing step causes a different test failure independently. Restoring only `commit` fixes the total but not the consistency check. Restoring only `freeze_view` fixes neither (freeze_view reads from `stable`, which is empty without commit).

## The Correct Fix

The reference fix (`reference_fixes/commit_gate.py`) restores both lines:

```python
def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    commit(st)       # FIX: restored -- sets frozen gate + sorts into stable
    freeze_view(st)  # FIX: restored -- rebuilds view from committed stable
    return st, materialize(st)
```

After the fix: `commit` sorts entries into `stable` and sets `frozen = True`. `freeze_view` rebuilds `view` from the sorted `stable`. Now `get_committed_total` returns 30, and `view_digest == committed_digest` (both sorted as `"a|b"`).

## What the Test Checks

1. `ingest(entries)["total"]` must not be `None` (requires `commit` for frozen gate).
2. `ingest(entries)["total"]` must equal 30 (requires correct committed data).
3. `ingest_and_verify(entries)["consistent"]` must be `True` (requires `freeze_view` to rebuild view from sorted stable).
4. `preview(entries)["frozen"]` must be `False` (preview must NOT call commit -- verifies that commit is in `process_batch`, not globally injected).
5. `preview(entries)["items"]` must have length 2.

## Why This Is Difficult for LLMs

- **But-for necessity:** Both `commit` and `freeze_view` are independently necessary. Restoring only one does not pass all tests. The model must identify BOTH missing steps.
- **The comments say "redundant."** The commented-out lines are labeled as removed because they were "redundant," which may mislead models into thinking they truly are unnecessary.
- **Input order matters:** The test uses entries `[{"id": "b", "val": 20}, {"id": "a", "val": 10}]` (intentionally unsorted). `stage` preserves this order in `view`. `commit` sorts by id into `stable`. Without `freeze_view`, the view digest is `"b|a"` but the committed digest is `"a|b"` -- inconsistent.
- **Preview constraint:** The model cannot "fix" the problem by adding commit/freeze to all paths -- `preview` must remain unfrozen. The fix must be specifically in `process_batch`.

## Causal Reasoning Required (L3)

### Pearl Level: Counterfactual

L3 reasoning requires but-for analysis: "But for the removal of `commit`, would the total be non-null? Yes -- but the view would still be inconsistent without `freeze_view`." And conversely: "But for the removal of `freeze_view`, would the view be consistent? No -- because without `commit`, `stable` is empty so `freeze_view` has nothing to work with." The model must reason about each missing step's independent causal contribution and recognize that both are necessary.

### Trap Type: Two absent steps each independently necessary

The trap is that the model may find one missing step and stop. Restoring `commit` alone fixes the `total is None` symptom but not the consistency check. The model must trace both failure paths to their respective missing causes, recognizing that the two steps serve different causal roles (commit: frozen gate + sort into stable; freeze_view: rebuild view from stable).

### Why This Case Is L3, Not L1 or L2

- **Not L1:** L1 would be observing "total is null and view is inconsistent." That describes symptoms, not causes.
- **Not L2:** L2 would be identifying one intervention (e.g., restore commit). But restoring only commit does not fix the consistency check. The model must reason about two independently necessary interventions.
- **L3 specifically:** The but-for structure -- two absent steps, each independently necessary, neither sufficient alone -- requires counterfactual reasoning about what each step contributes to the outcome. This is the hallmark of L3 causal analysis.

## Failure Mode Being Tested

Missing pipeline steps: two operations removed as "redundant" are each independently necessary for different invariants, requiring but-for counterfactual analysis to identify both.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely restores at most one of the two lines, or adds commit/freeze in the wrong location (e.g., in `api.py`). May break the preview constraint. |
| 4o-mini | partial | May restore `commit` (the more obvious fix for `total is None`) but miss `freeze_view` or not understand the sort-order consistency requirement. |
| 5-mini | partial/pass | Should trace both failure paths but may still miss the ordering subtlety (unsorted view vs. sorted stable) that makes `freeze_view` necessary. |
