# Case: stale_cache_a

**Family:** stale_cache
**Difficulty:** A (Easy)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1 Survivorship: missing call is invisible

---

## Task Prompt

> Refactor this product catalog for clarity. Return the updated code.

## What the Code Does

A single-file product catalog with an in-memory database and cache. Products are stored in `_db` and cached in `_cache` for faster lookups. The cache is populated on first read but never invalidated on write.

### Files

**catalog.py**
- `_db = {}` -- module-level dict acting as the database
- `_cache = {}` -- module-level dict acting as the read cache
- `add_product(product_id, name, price)` -- inserts a product into `_db`
- `get_product(product_id)` -- checks `_cache` first, falls through to `_db`, populates cache on miss
- `update_product(product_id, **fields)` -- updates product fields in `_db` but does NOT invalidate `_cache`
- `reset()` -- clears both `_db` and `_cache`

## The Bug

In `update_product`, line 29-30: after `_db[product_id].update(fields)`, the function returns without removing the stale entry from `_cache`. On the next call to `get_product(product_id)`, the cache still contains the old data, so the stale cached version is returned instead of the updated DB version.

The invariant violated: `get_product()` must return current data after `update_product()`.

## The Correct Fix

In `update_product`, after line 29 (`_db[product_id].update(fields)`), add cache invalidation:

```python
_db[product_id].update(fields)
_cache.pop(product_id, None)  # ADD: invalidate cache entry
return True
```

1 line added.

## What the Test Checks

1. `add_product("p1", "Widget", 10.0)` adds a product
2. `get_product("p1")` primes the cache (returns `{"name": "Widget", "price": 10.0}`)
3. `update_product("p1", price=25.0)` updates the price in the DB
4. `get_product("p1")` must return `{"price": 25.0}` (not stale `10.0`)

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" without mentioning any bug. An LLM doing cosmetic refactoring (renaming, type hints) will leave the missing invalidation intact.
- The bug is an absence: there is no wrong line of code, just a missing line. LLMs are generally better at fixing incorrect code than detecting missing code.
- `update_product` looks complete -- it updates the DB and returns True. The cache invalidation is entirely absent, not partially present.
- Survivorship bias: only the write path that exists (DB update) is visible. The write path that should exist (cache invalidation) has no trace in the code.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is associational: the model can observe that `get_product` reads from `_cache`, that `update_product` writes to `_db` but not `_cache`, and associate these observations to identify the stale read problem. No intervention reasoning is needed -- just noticing the asymmetry between the read path (cache-aware) and write path (cache-unaware).

### Trap Type: F1: Survivorship

The survivorship bias is that only the successful operations are visible in `update_product`. The DB update succeeds and the function returns True, creating the appearance of a complete operation. The missing cache invalidation is invisible because there is no failed operation, no error, no comment -- just an absence. You only see what survived into the code (DB write), not what was left out (cache invalidation).

### Why This Case Is L1, Not L2/L3

- L1 because the bug is identifiable within a single file by comparing the read path (cache -> DB) with the write path (DB only). The asymmetry is visible without cross-function reasoning.
- Not L2 because no intervention analysis or cross-file tracing is needed.
- Not L3 because no temporal reasoning or counterfactual simulation is required.

## Failure Mode Being Tested

Hidden dependency (cache coherence): the cache and database have a hidden dependency that must be maintained on writes. The write operation maintains the DB half of the dependency but not the cache half. This is the classic cache invalidation problem.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to miss the missing invalidation; will do cosmetic refactoring |
| 4o-mini | Heuristic | Cache invalidation is a well-known pattern; may recognize it from training data |
| 5-mini | CSF | Should identify the missing cache invalidation from the read/write asymmetry |

*These are hypotheses, not measurements.*
