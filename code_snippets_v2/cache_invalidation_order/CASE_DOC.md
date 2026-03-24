# Case: cache_invalidation_order

**Family:** Cache Ordering
**Difficulty:** Hard (V1)
**Bug Pattern:** CACHE_ORDERING
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F4 Direction + F6 Mechanism: remove cache_invalidate from update_record, breaking version tracking that safe_update's cache_conditional_set depends on

---

## Task Prompt

> update_record does invalidate then set, which seems redundant. Simplify the cache logic by removing the invalidation step and just writing directly. Return the updated code.

## What the Code Does

The system has four modules managing a cache with version tracking:

- **cache.py** provides versioned cache operations:
  ```python
  def cache_set(key, value, version=None):   # Unconditional set, stores version
  def cache_get(key):                         # Read value
  def cache_get_version(key):                 # Read version (-1 if missing)
  def cache_invalidate(key):                  # Remove key AND version
  def cache_conditional_set(key, value, expected_version):
      # Only writes if current version == expected_version, then increments version
  ```

- **db.py** provides simple key-value database operations.

- **service.py** implements two update patterns:
  ```python
  def update_record(key, value):
      ver = cache_get_version(key)      # Read current version
      db_write("records", key, value)    # Write to DB
      cache_invalidate(key)              # CLEAR cache + version
      cache_set(key, value, version=ver + 1)  # Re-set with incremented version

  def safe_update(key, value):
      ver = cache_get_version(key)      # Read current version
      db_write("records", key, value)    # Write to DB
      cache_conditional_set(key, value, ver)  # CAS: only if version matches
  ```

- **api.py** exposes `put` (uses `update_record`) and `safe_put` (uses `safe_update`).

The critical interaction: `update_record` does invalidate-then-set, which resets the version counter. `safe_update` uses `cache_conditional_set`, which checks the version. If `update_record` stops resetting versions, `safe_update`'s version checks may fail or produce incorrect results.

## The Bug

The buggy version (`service_buggy.py`) removes all cache operations from `update_record`:

```python
def update_record(key, value):
    db_write("records", key, value)
    # No cache_invalidate, no cache_set
```

After `update_record("k1", "v1")`, the cache is not populated. When `read_record("k1")` is called, it falls through to `db_read` and populates the cache via `cache_set(key, val)` (with `version=0`). Then after `update_record("k1", "v2")`, the cache still holds `"v1"` because `update_record` no longer touches the cache. `read_record("k1")` returns the stale `"v1"` from cache.

## The Correct Fix

The reference fix (`reference_fixes/cache_invalidation_order.py`) preserves the full invalidate-then-set sequence:

```python
def update_record(key, value):
    ver = cache_get_version(key)
    db_write("records", key, value)
    cache_invalidate(key)                    # Clears stale data AND resets version
    cache_set(key, value, version=ver + 1)   # Populates fresh data with new version
```

The invalidation step is NOT redundant -- it serves two purposes:
1. Removes stale cache data before the new write.
2. Resets the version counter so that `cache_conditional_set` in `safe_update` works with predictable version sequences.

## What the Test Checks

1. `update_record("k1", "v1")` -- writes to DB and cache.
2. `read_record("k1")` -- must return `"v1"` (from cache or DB).
3. `update_record("k1", "v2")` -- must update both DB and cache.
4. `read_record("k1")` -- must return `"v2"`, not the stale `"v1"`.

If `update_record` does not update the cache, the second `read_record` returns `"v1"` from the stale cache entry.

## Why This Is Difficult for LLMs

1. **The task explicitly calls it redundant:** "invalidate then set, which seems redundant" primes the model to remove the invalidation. On the surface, invalidate-then-set does look wasteful -- why delete something you're about to overwrite?

2. **Version tracking is the hidden mechanism:** The reason for invalidate-then-set is NOT just to update the value (which `cache_set` alone could do). It's to reset the version counter via `cache_invalidate`, which affects `cache_conditional_set` in `safe_update`. This cross-function dependency is non-obvious.

3. **Two update paths interact:** `update_record` and `safe_update` share the version state. The model must understand that changing `update_record`'s cache behavior affects `safe_update`'s correctness, even though they appear to be independent functions.

4. **The immediate test only checks basic read-after-write:** The test doesn't directly test `safe_update` or version semantics -- it tests the simpler property that `read_record` returns fresh data after `update_record`. But even this simpler property breaks when cache operations are removed.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about the intervention of removing `cache_invalidate` and `cache_set` from `update_record`:

1. Trace the first `update_record("k1", "v1")` -- without cache ops, only DB is written.
2. Trace `read_record("k1")` -- cache miss, falls through to DB, populates cache with `"v1"`.
3. Trace the second `update_record("k1", "v2")` -- again only DB is written, cache untouched.
4. Trace `read_record("k1")` -- cache hit returns stale `"v1"`.

Additionally, for the deeper version-tracking issue:
5. Understand that `cache_invalidate` resets the version counter.
6. Trace how `safe_update` reads version, then does `cache_conditional_set` which checks version equality.
7. Recognize that without invalidation resetting versions, the version sequence becomes unpredictable.

### Trap Type: F4 Direction + F6 Mechanism

**F4 (Direction):** The model sees invalidate -> set and reasons about the direction of data flow as: "data is removed then re-added, so the removal is unnecessary." But the causal direction is actually: invalidation resets state (version + data) so that the subsequent set starts from a clean baseline. The invalidation is a precondition for correct versioning, not a redundant predecessor of the set.

**F6 (Mechanism):** The model must understand the mechanism of version-tracked conditional sets. `cache_invalidate` removes the version entry, so `cache_get_version` returns `-1`. Then `cache_set` writes version `ver + 1`. Without the invalidate, the old version persists, and `cache_conditional_set` in `safe_update` may compare against a stale version.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug requires tracing through `cache.py`'s version tracking, `service.py`'s two update patterns, and the read-through caching in `read_record`. The interaction between `cache_invalidate`, `cache_set`, and `cache_conditional_set` spans multiple functions.
- **Not L3 (counterfactual):** The reasoning is forward-traceable: "If I remove invalidate and set from update_record, then read_record will return stale cache data." The causal chain is concrete and executable.
- **L2 (deep intervention):** The model must simulate the removal (intervention) and trace multi-step consequences through the cache read path and the version tracking system.

## Failure Mode Being Tested

CACHE_ORDERING -- The ordering of cache operations (invalidate before set) is semantically meaningful. Removing the invalidation step breaks both the data freshness guarantee and the version tracking contract that `safe_update` depends on.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will remove invalidation as the task instructs; cannot trace version tracking interactions |
| 4o-mini | CSF | Likely removes invalidation and possibly cache_set too, as the task says to "just write directly" |
| 5-mini | CSF | May keep cache_set but remove invalidate; unlikely to understand the version reset purpose |
