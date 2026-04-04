# Case: hidden_dep_multihop

**Family:** Hidden Dependency
**Difficulty:** Hard (V1)
**Bug Pattern:** HIDDEN_DEPENDENCY
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1 Survivorship + F3 Confounding: merge into one function using cache_put_if_absent (the safer-looking option), losing the always-overwrite behavior that save_user needs

---

## Task Prompt

> There are too many small cache helper functions doing similar things. Consolidate sync_user_to_cache and refresh_user_snapshot into a single function, then update all callers. Return the updated code.

## What the Code Does

The system has four modules managing user persistence and caching:

- **cache_writer.py** provides two cache-write functions with different semantics:
  - `cache_put(key, value)` -- always overwrites the cache entry.
  - `cache_put_if_absent(key, value)` -- only writes if the key does not already exist.
  - `sync_user_to_cache(user)` calls `cache_put` (always overwrites).
  - `refresh_user_snapshot(user)` calls `cache_put_if_absent` (won't overwrite).

- **cache_reader.py** provides `get_display_name(user_id)` which reads from `_store`.

- **user_repo.py** provides database persistence via `UserDB`.

- **user_service.py** wires together persistence and caching:
  - `save_user(user)` calls `persist_user` then `sync_user_to_cache` (always overwrites cache).
  - `rename_user(user_id, new_name)` updates the DB then calls `sync_user_to_cache` (overwrites cache).
  - `bulk_warm_cache(users)` calls `refresh_user_snapshot` (only populates missing entries).

## The Bug

When consolidating the two functions, the natural LLM instinct is to pick `cache_put_if_absent` as the "safer" unified implementation (it won't accidentally stomp data). The buggy version (`user_service_buggy.py`) replaces all calls to `sync_user_to_cache` with `refresh_user_snapshot`:

```python
# user_service_buggy.py line 6-7
def save_user(user):
    persist_user(user)
    refresh_user_snapshot(user)   # BUG: uses cache_put_if_absent
```

This means after `save_user({"id": "u1", "name": "Alice"})` followed by `save_user({"id": "u1", "name": "Bob"})`, the cache still holds "Alice" because `cache_put_if_absent` refuses to overwrite. `get_display_name("u1")` returns "Alice" instead of "Bob".

The bug is silent -- no exception is raised, no error is logged. The cache simply serves stale data.

## The Correct Fix

The reference fix (`reference_fixes/hidden_dep_multihop.py`) preserves `sync_user_to_cache` (which uses `cache_put`) for all write paths:

```python
def save_user(user):
    persist_user(user)
    sync_user_to_cache(user)      # cache_put -- always overwrites

def rename_user(user_id, new_name):
    ...
    if updated:
        sync_user_to_cache(updated)  # cache_put -- always overwrites

def bulk_warm_cache(users):
    for u in users:
        refresh_user_snapshot(u)     # cache_put_if_absent -- only warm missing
```

The key insight: these two functions are NOT redundant. They have different cache-write semantics required by their different callers. `save_user` and `rename_user` must always overwrite; `bulk_warm_cache` must not overwrite.

## What the Test Checks

1. `save_user({"id": "u1", "name": "Alice"})` -- then `get_display_name("u1")` must return `"Alice"`.
2. `save_user({"id": "u1", "name": "Bob"})` -- then `get_display_name("u1")` must return `"Bob"` (proving the cache was overwritten).

If the buggy consolidation is used, assertion 2 fails: the cache returns `"Alice"` because `cache_put_if_absent` did not overwrite.

## Why This Is Difficult for LLMs

1. **Survivorship bias (F1):** The two functions `sync_user_to_cache` and `refresh_user_snapshot` look almost identical at the call site -- both take a user dict and write to cache. The critical difference (`cache_put` vs `cache_put_if_absent`) is one hop away in `cache_writer.py`, not visible at the service layer.

2. **Confounding (F3):** The task prompt explicitly frames the functions as "doing similar things" and asks to "consolidate." This biases the model toward merging, which is the exact wrong move.

3. **The "safer" option is the trap:** `cache_put_if_absent` sounds more conservative and defensive -- exactly the kind of code LLMs prefer when uncertain. But it is the wrong choice for the write-through path.

4. **Multi-hop dependency:** Understanding the bug requires tracing: `save_user` -> `sync_user_to_cache` -> `cache_put` (always overwrites) vs `refresh_user_snapshot` -> `cache_put_if_absent` (conditional). Then tracing the read path: `get_display_name` -> `_store.get()`.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason: "If I intervene by replacing `sync_user_to_cache` with `refresh_user_snapshot` in `save_user`, what happens downstream?" This requires:

1. Tracing `sync_user_to_cache` -> `cache_put` (unconditional write).
2. Tracing `refresh_user_snapshot` -> `cache_put_if_absent` (conditional write).
3. Recognizing that `save_user` is called for updates (same user ID, new name).
4. Inferring that the conditional write will silently fail on the second save.
5. Tracing the read path through `get_display_name` to see the stale value.

### Trap Type: F1 Survivorship + F3 Confounding

**F1 (Survivorship):** The model sees two functions that both "write to cache" and concludes they're interchangeable. It doesn't observe the failure case (second write being silently dropped) because it only looks at the success case (first write works fine).

**F3 (Confounding):** The task prompt itself is a confound -- it tells the model to consolidate, creating a strong prior toward merging. The model conflates "similar interface" with "identical semantics."

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug is not visible in a single file or a single function call. It requires multi-hop tracing across `user_service.py` -> `cache_writer.py` -> `cache_reader.py`.
- **Not L3 (counterfactual):** The reasoning is forward-traceable: "If I replace X with Y, trace the execution to see what breaks." No counterfactual about what the world would look like if the code had never existed is needed. The causal chain is concrete and executable.
- **L2 (deep intervention):** The model must simulate an intervention (the consolidation) and trace its multi-step causal consequences through the write path and the read path.

## Failure Mode Being Tested

HIDDEN_DEPENDENCY -- The dependency between `save_user`'s need for unconditional cache writes and `sync_user_to_cache`'s use of `cache_put` is hidden behind a layer of indirection. The visible similarity between the two cache-write helpers masks a critical semantic difference.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace multi-hop dependencies; will merge functions based on surface similarity |
| 4o-mini | CSF | Likely follows task prompt and consolidates using the "safer" cache_put_if_absent |
| 5-mini | CSF | May trace one hop but unlikely to distinguish cache_put vs cache_put_if_absent semantics under consolidation pressure |
