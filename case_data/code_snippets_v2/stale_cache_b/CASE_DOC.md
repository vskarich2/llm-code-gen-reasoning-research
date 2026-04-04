# Case: stale_cache_b

**Family:** stale_cache
**Difficulty:** B (Medium)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1 Survivorship: missing call is invisible

---

## Task Prompt

> Products show old prices after updates. Fix the catalog. Return the updated code.

## What the Code Does

A two-file product catalog system. The cache is extracted into a separate module with explicit `get`, `put`, `invalidate`, and `clear` operations. The catalog module uses the cache for read-through caching but omits the `invalidate` call on writes.

### Files

**cache.py**
- `_store = {}` -- module-level cache storage
- `get(key)` -- returns cached value or None
- `put(key, value)` -- stores a value
- `invalidate(key)` -- removes a key from cache
- `clear()` -- clears entire cache

**catalog.py**
- `_db = {}` -- module-level database
- `add_product(product_id, name, price)` -- inserts into `_db`
- `get_product(product_id)` -- checks cache first via `cache.get()`, falls through to `_db`, populates cache via `cache.put()` on miss
- `update_product(product_id, **fields)` -- updates `_db` but does NOT call `cache.invalidate(product_id)`
- `reset()` -- clears both `_db` and cache

## The Bug

In `catalog.py`, lines 29-33: `update_product` updates `_db[product_id]` but never calls `invalidate(product_id)` from the imported cache module. The `invalidate` function is imported on line 3 (`from cache import get, put, invalidate`) but never used in `update_product`. After an update, `get_product` still returns the stale cached version.

The invariant violated: subsequent `get_product()` must reflect the update.

## The Correct Fix

In `catalog.py`, after line 31 (`_db[product_id].update(fields)`), add:

```python
_db[product_id].update(fields)
invalidate(product_id)  # ADD: invalidate stale cache entry
return True
```

1 line added.

## What the Test Checks

1. `add_product("p1", "Widget", 10.0)` adds a product
2. `get_product("p1")` primes the cache
3. `update_product("p1", price=25.0)` updates the DB price
4. `get_product("p1")` must return `{"price": 25.0}` (not stale `10.0`)

## Why This Is Difficult for LLMs

- The trap: `cache.py` has a `warm()` function (implied by the task description mentioning "cache.warm() exists but doesn't help"). However, looking at the actual code, `cache.py` provides `invalidate()` which is the correct function. The key trap is that `invalidate` is imported but never used -- an LLM must notice this unused import as a signal.
- The bug is in `catalog.py` but understanding why requires understanding `cache.py`'s API. The model must trace across the file boundary to understand that `invalidate` exists and is the correct intervention.
- `get_product` correctly uses `cache.get()` and `cache.put()`, suggesting the developer knows about the cache API. The omission of `cache.invalidate()` in `update_product` is a selective oversight.
- An LLM might try alternative fixes: updating the cache entry instead of invalidating it, or clearing the entire cache. While these might work, they are not the minimal correct fix.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about intervention: "What if I add `invalidate(product_id)` after the DB write?" This requires understanding the cache module's API (cross-file), identifying which function to call (`invalidate`, not `clear` or `put`), and reasoning about where in `update_product` to place the call. The model must also decide NOT to intervene in `cache.py` (which is correct) and intervene only in `catalog.py`.

### Trap Type: F1: Survivorship

The survivorship bias is the same as level A but compounded by the cross-file boundary. The `invalidate` function exists in `cache.py` and is even imported into `catalog.py`, but its absence from `update_product` is invisible. Only the surviving operations (DB update) appear in the write path. The `invalidate` import is a "survivor" that points to the fix, but an LLM may not notice that an imported function is unused.

### Why This Case Is L2, Not L1/L3

- Not L1 because the fix requires cross-file reasoning: understanding `cache.py`'s API and choosing the right function to call from `catalog.py`.
- L2 because the model must reason about which intervention (calling `invalidate` vs. other cache operations) will correctly break the stale-read causal chain.
- Not L3 because the causal chain is still a single write-then-read sequence, not a multi-step temporal scenario across many components.

## Failure Mode Being Tested

Hidden dependency across file boundaries: the cache and database are in separate modules, and the dependency (writes must invalidate cache) spans the boundary. The `invalidate` function's existence in cache.py is the key evidence, but its absence from the write path in catalog.py is the bug.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not trace the cross-file cache dependency |
| 4o-mini | REI | May notice the imported-but-unused invalidate function as a clue |
| 5-mini | CSF | Should identify the missing invalidate call from the import list and read/write asymmetry |

*These are hypotheses, not measurements.*
