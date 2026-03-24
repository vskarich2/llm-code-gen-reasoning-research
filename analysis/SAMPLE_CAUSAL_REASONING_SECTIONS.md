# Sample Causal Reasoning Sections

These are draft sections for the CASE_DOC.md files. Three L2 examples and four L3 examples showing how the causal reasoning requirement differs.

---

## L2 EXAMPLES

---

### stale_cache_b — Causal Reasoning Required (L2)

This case requires **L2 causal reasoning** — the model must trace a hidden write-read dependency across two modules to find the missing cache invalidation.

**The causal chain the model must discover:**

```
update_product(id, **fields)           [catalog.py]
    → _db[product_id].update(fields)   [catalog.py]  -- DB is now updated
    → (should call invalidate(id))     [cache.py]    -- BUT THIS IS MISSING

get_product(id)                        [catalog.py]
    → get(id)                          [cache.py]    -- returns STALE cached value
    → never reaches _db because cache hit
```

**Why this is L2, not L1 or L3:**

Not L1 because the bug is an **omission across a module boundary**. `update_product()` in `catalog.py` writes to `_db` but doesn't call `cache.invalidate()` — a function defined in `cache.py`. You cannot see the bug by reading `update_product()` alone; you must understand that `get_product()` checks the cache first, and that the cache is a separate module with its own `_store` dict. The causal chain crosses one boundary: write to DB (catalog) → stale read from cache (cache module).

Not L3 because there is only one cache layer and one write path. The model doesn't need to simulate multi-step state evolution or reason about execution ordering — it just needs to see that "write to DB" and "invalidate cache" must happen together, and the second is missing.

**The distractor:** `cache.warm()` exists and sounds relevant to "making the cache correct." But warming is for cold starts, not invalidation. Models that call `warm()` after `update_product()` would re-populate the cache with old data first, then overwrite — a timing-dependent fix that's fragile at best.

---

### effect_order_b — Causal Reasoning Required (L2)

This case requires **L2 causal reasoning** — the model must understand that `emit_event()` (defined in `metrics.py`) has a per-call contract that is violated when it's called once instead of N times.

**The causal chain the model must discover:**

```
process_batch(items)                   [processor.py]
    for item in items:
        increment(item["value"])       [metrics.py]  -- called N times (correct)
    emit_event(item["id"], ...)        [metrics.py]  -- called ONCE (BUG)

get_events()                           [metrics.py]
    → returns list with 1 event        -- should have N events
```

**Why this is L2, not L1 or L3:**

Not L1 because the invariant lives in `metrics.py`: `get_events()` is supposed to return one event per item processed. But the bug is in `processor.py`: `emit_event()` is outside the loop. The model must cross the boundary from "where the bug is" (processor) to "what the invariant is" (metrics) to understand why the placement matters.

Not L3 because both files have a simple call relationship — processor calls metrics functions. There's no multi-step state evolution, no execution ordering between independent subsystems, no hidden shared state. The dependency is one hop: loop body → side effect function.

**What makes this tricky:** The code runs without error. `emit_event()` after the loop still works — it emits one event for the last item. The output looks plausible. Only when you check `len(get_events()) == len(items)` does the violation appear. Models that focus on "does the code crash?" will miss this entirely.

---

### silent_default_b — Causal Reasoning Required (L2)

This case requires **L2 causal reasoning** — the model must trace a key-name mismatch through a nested config traversal across two files.

**The causal chain the model must discover:**

```
is_analytics_enabled()                 [flags.py]
    → get_flag("features.analytics.enabled")  -- "features" (plural)
    → traverses _CONFIG:
        _CONFIG["features"]?           [config.py]   -- KEY DOESN'T EXIST
        → falls through to default     -- silently returns False

But _CONFIG actually has:
    _CONFIG["feature"]["analytics"]["enabled"] = True   -- "feature" (singular)
```

**Why this is L2, not L1 or L3:**

Not L1 because the bug is a mismatch between two files. `flags.py` uses the path `"features.analytics.enabled"` while `config.py` defines the key as `"feature"` (singular). You must read both files and compare the key names to spot the discrepancy. Reading `flags.py` alone, the path looks reasonable.

Not L3 because the traversal is a direct lookup — there's no multi-step state evolution, no execution ordering, no shared mutable state. The model just needs to match a string in one file against a dict key in another. It's a static mismatch, not a dynamic one.

**What makes this difficult for LLMs:** The failure is completely silent. `get_flag()` is designed to return `default` on missing keys — that's its API contract. The model must realize that a silent default is **masking a bug**, not providing a graceful fallback. The distractor `validate_config()` only checks top-level keys, so it won't catch this. And the key difference is a single character: "feature" vs "features."

---

## L3 EXAMPLES

---

### alias_config_c — Causal Reasoning Required (L3)

This case requires **L3 causal reasoning** — the model must trace a shared reference through three files and understand how mutation in one request pollutes another.

**The causal chain the model must discover:**

```
handle_request({"debug": True})        [handler.py]
    → ConfigMiddleware()               [middleware.py]
        → self._base = create_config() [config.py]   -- returns REFERENCE to DEFAULTS
    → mw.apply_config({"debug": True}) [middleware.py]
        → cfg = self._base             -- same object as DEFAULTS
        → cfg.update({"debug": True})  -- MUTATES DEFAULTS via shared reference

handle_request()                       [handler.py]  -- second request, no overrides
    → ConfigMiddleware()               [middleware.py]
        → self._base = create_config() [config.py]   -- DEFAULTS is now {"debug": True, ...}
    → returns {"debug": True}          -- WRONG: should be False
```

**Why this is L3, not L2:**

The model must follow a **three-file chain**: `handler.py` → `middleware.py` → `config.py`, and understand that the mutation in middleware propagates BACK to config's `DEFAULTS` dict, which then affects ALL future calls. This is not a single call-boundary trace — it requires understanding that:

1. `create_config()` returns a reference (not a copy) — **config.py**
2. `ConfigMiddleware.__init__` captures this reference — **middleware.py**
3. `apply_config()` mutates it via `.update()` — **middleware.py**
4. This mutation persists in `DEFAULTS` — **back to config.py**
5. The next `create_config()` call returns the mutated dict — **affects handler.py**

This is a **state evolution cycle** across three modules: config → middleware → config (mutated) → handler (sees wrong state).

**The trap:** `merge_overrides()` in `config.py` correctly uses `dict(base)` (makes a copy). It's tempting to route middleware through `merge_overrides()` instead of fixing `create_config()`. But `merge_overrides()` has a different return type semantic and would change the middleware API. The correct fix is a one-line change in `create_config()`: `config = DEFAULTS` → `config = DEFAULTS.copy()`. Finding this requires tracing all three files to realize the root cause is in `config.py`, not `middleware.py`.

---

### retry_dup_c — Causal Reasoning Required (L3)

This case requires **L3 causal reasoning** — the model must simulate the execution of two nested retry loops across three files to count how many times a message is stored.

**The causal chain the model must discover:**

```
ingest(msg, fail_first=False)          [pipeline.py]
    for attempt in range(2):           -- pipeline retry loop
        send_with_retry(msg)           [sender.py]
            for attempt in range(2):   -- sender retry loop
                send(msg)              [sender.py]
                    append(msg)        [store.py]  -- message stored
                    notify(msg)        [store.py]  -- notification sent
                    break              -- sender exits on success
        # BUG: no break in pipeline loop — goes around again
        send_with_retry(msg)           -- SECOND call
            send(msg)
                append(msg)            -- message stored AGAIN

Result: msg appears 2x in store (or more with fail_first=True)
```

**Why this is L3, not L2:**

L2 would be understanding that `send()` appends to a store (one boundary). L3 requires understanding the **interaction between two retry loops in different files**. The model must mentally execute:

1. Pipeline calls `send_with_retry()` — **pipeline.py → sender.py**
2. `send_with_retry()` calls `send()` which calls `store.append()` — **sender.py → store.py**
3. `send_with_retry()` breaks on success — **correct behavior**
4. But `ingest()` doesn't break — **back to pipeline.py** — loops again
5. Second iteration calls `send_with_retry()` again — **pipeline.py → sender.py → store.py**
6. Message is now in store twice

This requires simulating control flow across three modules with nested loops — the model must track which loop has a `break` and which doesn't, and count the total number of `append()` calls that result. The trap: adding more retry at the pipeline level (the intuitive "make it more robust" fix) actually makes the duplication worse.

---

### early_return_c — Causal Reasoning Required (L3)

This case requires **L3 causal reasoning** — the model must understand that a caching optimization in `payment.py` creates a code path that skips an audit call in a third module, and that this skip is the bug even though the caching is correct.

**The causal chain the model must discover:**

```
charge(txn_id, amount)                 [payment.py]
    if txn_id in _charge_cache:        -- cache hit (CORRECT optimization)
        return _charge_cache[txn_id]   -- early return, SKIPS everything below

    result = {...}
    record(txn_id, amount, "charged")  [ledger.py]   -- ledger entry
    log_charge(txn_id, amount)         [audit.py]    -- audit entry
    _charge_cache[txn_id] = result
    return result

# Second call with same txn_id:
charge(same_txn_id, amount)            [payment.py]
    → cache hit → return early
    → record() NOT called              -- OK (no double-charge in ledger)
    → log_charge() NOT called          -- BUG (audit must log ALL calls)

audit.verify_completeness(2)           [audit.py]
    → len(_log) == 1, expected 2       -- FAILS
```

**Why this is L3, not L2:**

The model must reason about three modules simultaneously and make a **nuanced distinction**:

1. The caching is **correct** — skipping `record()` is right (no double-charge) — **payment.py + ledger.py**
2. But skipping `log_charge()` is **wrong** — audit must record every call for compliance — **payment.py + audit.py**
3. The model must understand the **different contracts** of two downstream modules (ledger = financial correctness, audit = completeness) and realize only one is satisfied by the early return

This is harder than a simple "missing call" because the model must distinguish between two seemingly identical omissions (both are skipped by the early return) and recognize that one is correct (ledger) and one is a bug (audit). This requires understanding the separate contracts of `ledger.py` and `audit.py` — a three-module analysis.

**The trap:** The caching itself looks suspicious. Models may try to remove the cache or add double-charge protection, which is unnecessary and changes the (correct) financial behavior. The bug is specifically that `log_charge()` is missing on the cached path — the fix is to add `log_charge()` before the early return, not to remove the cache.

---

### temporal_drift_c — Causal Reasoning Required (L3)

This case requires **L3 causal reasoning** — the model must trace which representation of the data (original vs. normalized) reaches which function across a 4-stage pipeline spanning three files.

**The causal chain the model must discover:**

```
pipeline(data)                         [pipeline.py]
    normalized = normalize(data)       [transforms.py]  -- data → 0-1 range
    clipped = clip(normalized, ...)    [transforms.py]  -- clips to 0.05-0.95
    raw_stats = compute_raw_stats(normalized)  [metrics.py]
                                       ↑ BUG: should be data, not normalized
    display = summarize_for_display(clipped)   [transforms.py]

raw_stats["raw_max"]                   -- returns ~1.0 (normalized max)
                                       -- should return actual max of original data
```

**Why this is L3, not L2:**

The model must trace **which data flows where** across three files:

1. `data` (original) is the input — **pipeline.py**
2. `normalize()` transforms it to 0-1 range — **transforms.py** — producing `normalized`
3. `compute_raw_stats()` receives `normalized` but should receive `data` — **metrics.py** — the bug is in **pipeline.py**'s wiring
4. The invariant (raw_max must equal the actual maximum) is defined by `compute_raw_stats`'s contract — **metrics.py**
5. `summarize_for_display()` has **different key names** (display_max vs raw_max) — **transforms.py** — making it a trap for consolidation

This is a 3-file data-flow analysis. The model must understand that `normalized` and `data` are different representations, that `compute_raw_stats` has a semantic contract requiring the original representation, and that the similar-looking `summarize_for_display` is NOT a replacement (different keys, different input stage). The stages are intentionally scrambled in the code (normalize → clip → raw_stats instead of raw_stats → normalize → clip) to test whether the model reasons about data flow or just follows code order.

**The trap:** `summarize_for_display()` computes max/min/mean on cleaned data — it looks like a more convenient version of `compute_raw_stats()`. But it returns `display_max`, `display_min`, `display_mean` — not `raw_max`, `raw_min`, `raw_sum`, `raw_count`. Consolidating them breaks all downstream consumers that read `raw_*` keys. This is the `implicit_schema` bug pattern: two functions look similar but have different contracts.
