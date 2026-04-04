# Case: stale_cache_c

**Family:** stale_cache
**Difficulty:** C (Hard)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1 Survivorship: missing call is invisible

---

## Task Prompt

> API returns stale product data despite updates. Fix the caching issue. Return the updated code.

## What the Code Does

A three-file product system with a two-layer cache architecture. The cache module provides separate local (per-request) and shared (global) cache layers. The catalog module manages the database and invalidates the shared cache on writes. The API module reads through both cache layers (local first, then shared, then DB). The bug: `update_product` invalidates the shared cache but NOT the local cache.

### Files

**cache.py**
- `_local = {}` -- local cache (per-request fast path)
- `_shared = {}` -- shared cache (global)
- `get_local(key)` / `put_local(key, value)` / `invalidate_local(key)` -- local cache operations
- `get_shared(key)` / `put_shared(key, value)` / `invalidate_shared(key)` -- shared cache operations
- `clear_all()` -- clears both layers

**catalog.py**
- `_db = {}` -- database
- `add_product(product_id, name, price)` -- inserts into DB
- `db_get(product_id)` -- raw DB lookup returning a copy
- `update_product(product_id, **fields)` -- updates DB, calls `invalidate_shared(product_id)`, but does NOT call `invalidate_local(product_id)`
- `reset()` -- clears DB

**api.py**
- `get_product(product_id)` -- reads through: local cache -> shared cache -> DB; populates both caches on miss
- `format_product(product_id)` -- display formatter (distractor)

## The Bug

In `catalog.py`, lines 26-29: `update_product` calls `invalidate_shared(product_id)` after the DB update, but does NOT call `invalidate_local(product_id)`. The `invalidate_local` function is imported on line 3 but never used.

When `api.get_product` runs after an update:
1. It checks local cache first (`get_local`) -- finds the STALE entry (local was never invalidated)
2. Returns the stale data without ever reaching the shared cache or DB

The shared cache invalidation is correct but irrelevant because the local cache short-circuits the lookup.

## The Correct Fix

In `catalog.py`, after `invalidate_shared(product_id)` (line 27), add:

```python
invalidate_shared(product_id)
invalidate_local(product_id)  # ADD: must also invalidate local cache
return True
```

1 line added.

## What the Test Checks

1. `add_product("p1", "Widget", 10.0)` adds a product
2. `get_product("p1")` primes BOTH cache layers (local and shared)
3. `update_product("p1", price=50.0)` updates the DB and invalidates shared cache
4. `get_product("p1")` must return `{"price": 50.0}` (not stale `10.0` from local cache)

## Why This Is Difficult for LLMs

- The major trap: `invalidate_shared(product_id)` IS called in `update_product`, making it look like cache invalidation is handled. An LLM that sees any cache invalidation call may conclude the write path is correct. The partial fix is more deceptive than no fix at all.
- The two-layer cache architecture requires understanding the read-through order: local -> shared -> DB. The LLM must realize that invalidating only the shared layer is insufficient because the local layer is checked first.
- `invalidate_local` is imported but unused -- the same pattern as level B, but harder to notice because `invalidate_shared` IS used, making the imports look complete at a glance.
- The `format_product` function in `api.py` is a distractor that adds code volume without contributing to the bug.
- An LLM might try to fix the read path in `api.py` (e.g., skip local cache after updates) instead of fixing the write path in `catalog.py`.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

This requires multi-step causal propagation across multiple components and layers. The model must perform deterministic state tracing across modules: follow the read-through sequence (`get_local` -> `get_shared` -> `db_get`) and verify the mechanism at each layer. It must trace that `update_product` calls `invalidate_shared` but not `invalidate_local`, then perform forward path analysis through `api.get_product` to see that the local cache still holds stale data, short-circuiting the lookup before it reaches the (correctly invalidated) shared cache or DB.

### Trap Type: F1: Survivorship

The survivorship bias is particularly insidious here. The `invalidate_shared` call SURVIVED into the code, making the write path look like it handles cache invalidation. The missing `invalidate_local` call is invisible -- it didn't survive. The presence of one correct invalidation call masks the absence of the other. This is a higher-order survivorship bias: not just "missing code is invisible" but "partially-present code makes the missing part even more invisible."

### Why This Case Is L2 (deep), Not L1 or L3

- Not L1 because the bug requires understanding three files and a two-layer cache architecture. No single file reveals the problem.
- L2 (deep) because the model must perform multi-step causal propagation through a layered architecture: trace the write path (which invalidation calls are made), then trace the read path (which cache layer is checked first), and verify the mechanism at each step. This is deterministic state tracing across modules -- hard, but entirely forward-path analysis.
- Not L3 because all steps are deterministic -- the model follows code paths, not alternative worlds. There is no need to compare two hypothetical executions; the model simply traces what the code actually does step by step across three files.

## Failure Mode Being Tested

Hidden dependency in a multi-layer cache system: the local and shared caches both depend on the database, but the write path only maintains one dependency. The partial invalidation creates a false sense of correctness. This tests whether the model can identify incomplete cache coherence in a layered architecture.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Very unlikely to understand two-layer cache semantics or trace the read-through path |
| 4o-mini | CSF | May be fooled by the existing invalidate_shared call into thinking invalidation is handled |
| 5-mini | CSF | Best chance but the partial-fix trap is challenging even for strong models |

*These are hypotheses, not measurements.*
