# Case: use_before_set_c

**Family:** use_before_set
**Difficulty:** C (Hard)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F5: Information bias (empty/edge input is invisible path)

---

## Task Prompt

> Processing crashes when no items match filter. Fix. Return the updated code.

## What the Code Does

A three-file pipeline system for loading, validating, and searching records.

**validator.py** defines rule functions (e.g., `non_negative`, `under_limit`) and a `check_rule()` function.

**loader.py** uses the validator to filter records:
```python
def load_and_validate(records, rules):
    valid = []
    for record in records:
        passes = all(check_rule(r, record["value"]) for r in rules)
        if passes:
            valid.append(record)
    _loaded = valid
    _load_status = "validated"
    return valid, _load_status
```

**pipeline.py** contains the buggy `find_best()` function:
```python
def find_best(records, rules):
    global _pipeline_result, _last_best
    valid, status = load_and_validate(records, rules)
    threshold = 50
    for rec in valid:
        if rec["value"] > threshold:
            best = rec
            _last_best = best
            break
    else:
        best = _last_best  # BUG: uses stale _last_best from previous call
    _pipeline_result = "found" if best is not None else "not_found"
    return best
```

The contract: `find_best` must return `None` when no records exceed the threshold. Instead, it returns the result from a previous call.

## The Bug

In `find_best()`, the `for/else` construct sets `best = _last_best` when no record exceeds the threshold. If a previous call set `_last_best` to a valid record, subsequent calls where no record qualifies will silently return that stale record instead of `None`.

The bug involves three interacting components:
1. `validator.py` determines which records pass rules (all pass `non_negative` in the test)
2. `loader.py` filters and returns validated records
3. `pipeline.py` searches the filtered records but falls back to stale state

## The Correct Fix

Initialize `best = None` before the loop and do not fall back to `_last_best`:

```python
def find_best(records, rules):
    global _pipeline_result, _last_best
    valid, status = load_and_validate(records, rules)
    threshold = 50
    best = None
    for rec in valid:
        if rec["value"] > threshold:
            best = rec
            _last_best = best
            break
    _pipeline_result = "found" if best is not None else "not_found"
    return best
```

**Lines changed:** ~6 (add `best = None` initialization, remove `else: best = _last_best` fallback)

## What the Test Checks

1. Reset module state
2. Call `find_best([{"id": "h1", "value": 100}], ["non_negative"])` -- finds record above threshold
3. Call `find_best([{"id": "l1", "value": 10}, {"id": "l2", "value": 20}], ["non_negative"])` -- no record above threshold
4. **Assert:** second call returns `None` (not the stale `{"id": "h1", "value": 100}` from first call)

## Why This Is Difficult for LLMs

- **Three-file trace required:** The model must understand the validation pipeline (`validator` -> `loader` -> `pipeline`) to confirm that the low-value records pass validation but fail the threshold check.
- **Python for/else is uncommon:** Many developers (and models) misunderstand the `for/else` construct. The `else` block runs when the loop completes without `break`, not when the loop body has no iterations. Models may not reason correctly about when `best = _last_best` executes.
- **Distractor: `set_threshold()`** is defined in `pipeline.py` as a no-op. It looks like it could be the fix point ("just lower the threshold"), but it does nothing and adjusting the threshold is wrong anyway.
- **Trap: adding default inside loop (wrong scope).** A model might add `best = None` inside the loop body, which would be overwritten on each iteration and still fail.
- **Multi-call statefulness:** The bug only manifests on the SECOND call. The first call works correctly. Models that reason about single executions miss the cross-call state leak.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform deterministic state tracing across modules through a multi-step execution sequence: trace the first call setting `_last_best = {"id": "h1", ...}`, then trace the second call where no records exceed the threshold, following the `for/else` construct to see that `best = _last_best` reads the stale value. This is forward path analysis through three files across two invocations -- multi-step causal propagation tracking state evolution through the validator/loader/pipeline chain.

### Trap Type: F5: Information bias (empty/edge input is invisible path)

The "no records exceed threshold" path is the invisible one. Training data overwhelmingly shows search functions finding results. The fallback to `_last_best` looks like a reasonable caching strategy rather than a stale-state bug.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug involves three files and the stale state only manifests across multiple calls. Local analysis of `find_best` alone does not reveal the failure without understanding the validator/loader chain and the multi-call state accumulation.

**L2 (deep)** because the model must trace multiple cross-file hops (`validator.check_rule` -> `loader.load_and_validate` -> `pipeline.find_best` -> `_last_best` persistence) and track state evolution across two sequential invocations. This is multi-step causal propagation through three modules with mechanism verification at each step.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The `for/else` semantics, the state mutation, and the stale read are all directly traceable through the actual execution path.

## Failure Mode Being Tested

**USE_BEFORE_SET** (edge_case_omission) -- a variable set in a loop body is read after the loop, falling back to stale state when the loop does not set it. The three-file architecture and multi-call statefulness make this a hard case for edge-case detection.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace 3-file state evolution across multiple calls |
| 4o-mini | CSF | for/else semantics plus cross-file state is beyond typical capability |
| 5-mini | CSF | May identify the stale state but struggle with the correct scope for initialization |
