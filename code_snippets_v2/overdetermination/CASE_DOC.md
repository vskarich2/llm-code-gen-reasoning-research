# Case: overdetermination

**Family:** state management / caching
**Difficulty:** hard
**Bug Pattern:** stale cache overwrites fresh data
**Causal Depth:** 2 deep
**Pearl Level:** L2
**Trap Type:** F3: confounding (cache is hidden shared state)

---

## Task Prompt

> Fix the product update system so that after two updates with different values, the store contains the latest value.

## What the Code Does

The case spans four files:

**`store.py`** -- a key-value store with version tracking:
```python
def write(key, value, version=None):
    _data[key] = value
    if version is not None:
        _versions[key] = version
```

**`writer_a.py`** -- a "fresh" writer that always computes and writes with version tracking:
```python
def write_fresh(key, compute_fn):
    global _counter
    _counter += 1
    value = compute_fn()
    write(key, value, version=_counter)
    return value
```

**`writer_b.py`** -- a "cached" writer that caches the first computed value and replays it:
```python
def write_cached(key, compute_fn):
    if key not in _cache:
        _cache[key] = compute_fn()
    write(key, _cache[key])  # no version update
    return _cache[key]
```

**`api.py`** -- calls both writers in sequence:
```python
def update_product(product_id, compute_fn):
    write_fresh(product_id, compute_fn)
    write_cached(product_id, compute_fn)
    return read(product_id)
```

## The Bug

On the first call `update_product("P1", lambda: 42)`:
1. `write_fresh("P1", ...)` computes 42, writes `store["P1"] = 42` with version=1.
2. `write_cached("P1", ...)` cache miss, computes 42, caches it, writes `store["P1"] = 42` (no version). Store value: 42. Correct.

On the second call `update_product("P1", lambda: 99)`:
1. `write_fresh("P1", ...)` computes 99, writes `store["P1"] = 99` with version=2.
2. `write_cached("P1", ...)` cache HIT, reads cached value 42, writes `store["P1"] = 42` (no version). Store value: 42. **Bug -- should be 99.**

The stale cached value (42) from `writer_b` overwrites the fresh value (99) from `writer_a`. The bug is silent on the first call because both writers compute the same value.

## The Correct Fix

The reference fix (`reference_fixes/overdetermination.py`) removes the `write_cached` call entirely:

```python
def update_product(product_id, compute_fn):
    """Update product data. Uses fresh writer only."""
    write_fresh(product_id, compute_fn)
    return read(product_id)
```

The cached writer is redundant and harmful. Since `write_fresh` always computes the current value and writes it with version tracking, the cached writer only serves to potentially overwrite fresh data with stale cached data.

## What the Test Checks

1. After `update_product("P1", lambda: 42)` then `update_product("P1", lambda: 99)`, `serve_request("P1")["value"]` must equal 99.

The test calls `reset()` if available, then performs two updates with different values and checks that the final stored value is the latest one (99, not 42).

## Why This Is Difficult for LLMs

- **F3 confounding: cache is hidden shared state.** The `_cache` dict in `writer_b.py` is the hidden confounding variable. It is never passed as a parameter and is not visible from `api.py`. The model must trace through the module boundary to discover that `write_cached` replays a stale value.
- **First call masks the bug.** On the first call, both writers produce the same result (42). The bug only manifests on the second call with a different value. Models that test only one call will not detect the issue.
- **Common wrong fix: invalidating the cache.** A model might add cache invalidation in `write_cached`, making it always recompute. This fixes the test but retains the redundant double-write pattern. The structural fix is to remove the cached writer call entirely.
- **Common wrong fix: swapping writer order.** Calling `write_cached` before `write_fresh` would make the test pass (fresh writer writes last), but leaves the stale-cache bug latent -- any future code reading from cache or reordering writers would re-expose it.
- **The "redundant" double-write pattern.** The api calls both writers, which appears to be a belt-and-suspenders approach. The model must recognize that the second write is not just redundant but actively harmful.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention (deep)

This is L2 "deep" because the model must trace the causal chain across three modules (api -> writer_b -> store) and identify that the hidden cache state in `writer_b` is the root cause. The intervention is removing the `write_cached` call, but arriving at this requires understanding the temporal interaction between two writers sharing a store.

### Trap Type: F3: confounding (cache is hidden shared state)

The `_cache` dict in `writer_b.py` is a confounding variable. It is:
- **Hidden:** Not visible in the `api.py` call site. The function signature `write_cached(key, compute_fn)` gives no indication of caching.
- **Shared state:** Persists across calls, creating temporal coupling between the first and second `update_product` invocations.
- **Confounding:** It makes the second `write_cached` call appear to "work" (it returns a value and writes to the store) while actually overwriting the correct fresh value with a stale one.

### Why This Case Is L2 Deep, Not L1 or L3

- **Not L1:** L1 would be observing "the store has 42 instead of 99." The model must trace through the call chain to find the cause.
- **L2 deep:** The causal chain spans three modules and involves hidden shared state (the cache). The model must reason about temporal state across two `update_product` calls and identify which writer's output is final. This is deeper than a single-module intervention.
- **Not L3:** L3 requires structural vs. contingent distinction or but-for multi-factor analysis. Here there is one cause (the `write_cached` call in `api.py`) and one fix (remove it). The complexity is in tracing the cause, not in distinguishing structural from contingent factors.

## Failure Mode Being Tested

Stale cache overwrite: a caching writer replays an outdated value, silently overwriting a fresh value written by another component.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely does not trace through the multi-module call chain. May try to fix `writer_b.py`'s cache logic rather than removing the call in `api.py`. |
| 4o-mini | partial | May identify the caching issue but add cache invalidation rather than removing the redundant call. Could also swap writer order. |
| 5-mini | pass | Should trace the full chain and identify that removing `write_cached` from `api.py` is the clean fix. |
