# Master Case Documentation — All Benchmark Cases

**Generated:** 2026-03-24
**Total cases documented:** 58
**Location:** All cases live in `code_snippets_v2/{case}/`

---

## Table of Contents

1. [alias_config_a](#alias-config-a)
2. [alias_config_b](#alias-config-b)
3. [alias_config_c](#alias-config-c)
4. [async_race_lock](#async-race-lock)
5. [cache_invalidation_order](#cache-invalidation-order)
6. [check_then_act](#check-then-act)
7. [commit_gate](#commit-gate)
8. [config_shadowing](#config-shadowing)
9. [early_return_a](#early-return-a)
10. [early_return_b](#early-return-b)
11. [early_return_c](#early-return-c)
12. [effect_order_a](#effect-order-a)
13. [effect_order_b](#effect-order-b)
14. [effect_order_c](#effect-order-c)
15. [false_fix_deadlock](#false-fix-deadlock)
16. [feature_flag_drift](#feature-flag-drift)
17. [hidden_dep_multihop](#hidden-dep-multihop)
18. [index_misalign_a](#index-misalign-a)
19. [index_misalign_b](#index-misalign-b)
20. [index_misalign_c](#index-misalign-c)
21. [invariant_partial_fail](#invariant-partial-fail)
22. [l3_state_pipeline](#l3-state-pipeline)
23. [lazy_init_a](#lazy-init-a)
24. [lazy_init_b](#lazy-init-b)
25. [lazy_init_c](#lazy-init-c)
26. [lost_update](#lost-update)
27. [missing_branch_a](#missing-branch-a)
28. [missing_branch_b](#missing-branch-b)
29. [missing_branch_c](#missing-branch-c)
30. [mutable_default_a](#mutable-default-a)
31. [mutable_default_b](#mutable-default-b)
32. [mutable_default_c](#mutable-default-c)
33. [ordering_dependency](#ordering-dependency)
34. [overdetermination](#overdetermination)
35. [partial_rollback_a](#partial-rollback-a)
36. [partial_rollback_b](#partial-rollback-b)
37. [partial_rollback_c](#partial-rollback-c)
38. [partial_update_a](#partial-update-a)
39. [partial_update_b](#partial-update-b)
40. [partial_update_c](#partial-update-c)
41. [retry_dup_a](#retry-dup-a)
42. [retry_dup_b](#retry-dup-b)
43. [retry_dup_c](#retry-dup-c)
44. [silent_default_a](#silent-default-a)
45. [silent_default_b](#silent-default-b)
46. [silent_default_c](#silent-default-c)
47. [stale_cache_a](#stale-cache-a)
48. [stale_cache_b](#stale-cache-b)
49. [stale_cache_c](#stale-cache-c)
50. [temporal_drift_a](#temporal-drift-a)
51. [temporal_drift_b](#temporal-drift-b)
52. [temporal_drift_c](#temporal-drift-c)
53. [use_before_set_a](#use-before-set-a)
54. [use_before_set_b](#use-before-set-b)
55. [use_before_set_c](#use-before-set-c)
56. [wrong_condition_a](#wrong-condition-a)
57. [wrong_condition_b](#wrong-condition-b)
58. [wrong_condition_c](#wrong-condition-c)

---

<a id="alias-config-a"></a>

# Case: alias_config_a

**Family:** alias_config
**Difficulty:** A (Easy)
**Bug Pattern:** implicit_schema
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F3 Confounding: shared mutable object is hidden common cause

---

## Task Prompt

> Refactor this configuration module for clarity. Return the updated code.

## What the Code Does

A single-file configuration module. A module-level `DEFAULTS` dict holds default config values. `create_config()` is supposed to return a new config dict based on those defaults, optionally merging in overrides. `reset_defaults()` restores the global `DEFAULTS` to factory values.

### Files

**config.py**
- `DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}` -- module-level default config dict
- `create_config(overrides=None)` -- intended to return a fresh config; actually returns a reference to `DEFAULTS`
- `reset_defaults()` -- reassigns `DEFAULTS` to a fresh factory dict

## The Bug

Line 6: `config = DEFAULTS` assigns by reference, not by copy. The returned dict IS the `DEFAULTS` dict. When the caller calls `config.update(overrides)` on line 8, it mutates `DEFAULTS` itself. Subsequent calls to `create_config()` without overrides will return a corrupted `DEFAULTS` that still contains the previous caller's overrides. The invariant violated: `create_config` must return a dict independent of `DEFAULTS`.

## The Correct Fix

```python
config = DEFAULTS.copy()  # was: config = DEFAULTS
```

Change line 6. 1 line changed.

## What the Test Checks

1. `create_config({"timeout": 5})` is called, then `create_config()` is called with no overrides
2. The second call's result must have `timeout == 30` (original default), not `5` (leaked override)
3. `DEFAULTS["timeout"]` must still be `30` after both calls

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" which does not mention a bug at all. An LLM focused on surface-level refactoring (renaming, docstrings, type hints) will leave the aliasing intact.
- `config = DEFAULTS` looks like a normal Python assignment. The mutation path through `.update()` is only visible when you trace what happens across two successive calls.
- No error is raised. The code runs without exceptions; the corruption is silent.
- An LLM that pattern-matches "return DEFAULTS" may not flag it because assignment-by-reference is extremely common in Python.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is an associational task: the bug is visible by observing the relationship between `config` and `DEFAULTS` in a single function. You see `config = DEFAULTS` and can recognize from Python semantics that they are the same object. No intervention or counterfactual reasoning is required -- just recognizing the aliasing pattern.

### Trap Type: F3: Confounding

The shared mutable `DEFAULTS` dict is the hidden common cause (confounder). Both `create_config()` calls appear independent, but they share state through `DEFAULTS`. The confounding structure: `DEFAULTS` causally affects both call 1's return value and call 2's return value. Mutations via call 1 propagate to call 2 through this shared reference.

### Why This Case Is L1, Not L2/L3

- L1 because the bug is locatable within a single function (`create_config`) by reading the code. No cross-function tracing is needed. No intervention reasoning ("what if I copy?") is required to identify the problem -- only recognition of the aliasing pattern.
- Not L2 because there is no need to trace across function boundaries or reason about what interventions would break the causal path.
- Not L3 because there is no multi-step temporal sequence or counterfactual reasoning about alternative code structures required.

## Failure Mode Being Tested

Implicit schema violation: the code implicitly assumes `create_config` returns an independent dict (a schema contract), but the implementation violates this by returning a shared reference. This is a classic Python aliasing pitfall where value semantics are expected but reference semantics are delivered.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI (Random/Entropy/Ignorant) | Likely to miss the aliasing entirely; may do cosmetic refactoring only |
| 4o-mini | Heuristic | May recognize `dict.copy()` pattern from training data but not reliably |
| 5-mini | CSF (Correct Sufficient Fix) | Strong enough to recognize the aliasing pattern in a single file |

*These are hypotheses, not measurements.*

---

<a id="alias-config-b"></a>

# Case: alias_config_b

**Family:** alias_config
**Difficulty:** B (Medium)
**Bug Pattern:** implicit_schema
**Causal Depth:** L1-L2 boundary
**Pearl Level:** L1-L2 Boundary (deterministic state tracing, not intervention reasoning)
**Trap Type:** F3 Confounding: shared mutable object is hidden common cause

---

## Task Prompt

> get_settings() returns stale data after config changes. Simplify the config loading. Return the updated code.

## What the Code Does

A two-file configuration system. `config.py` provides default config creation. `app.py` provides a caching layer on top of config and a function to apply runtime overrides.

### Files

**config.py**
- `DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}` -- module-level default config
- `create_config(overrides=None)` -- returns `DEFAULTS` by reference (BUG), with optional overrides applied
- `merge_overrides(base, overrides)` -- correctly copies `base` via `dict(base)` before merging (TRAP: looks like it does the right thing)
- `reset_defaults()` -- reassigns `DEFAULTS` to factory values

**app.py**
- `_cached_settings = None` -- module-level cache
- `get_settings()` -- lazy-loads settings via `create_config()`, caches the result
- `apply_overrides(overrides)` -- gets cached settings and mutates them via `.update()`
- `clear_cache()` -- sets `_cached_settings = None`

## The Bug

In `config.py` line 6: `config = DEFAULTS` returns the DEFAULTS dict by reference. When `app.py`'s `get_settings()` calls `create_config()`, the cached result IS `DEFAULTS`. When `apply_overrides()` mutates the cached settings, it directly mutates `DEFAULTS`. Subsequent calls to `create_config()` (even after `clear_cache()`) return the corrupted `DEFAULTS`.

The invariant violated: `create_config` must return a dict independent of `DEFAULTS`.

## The Correct Fix

In `config.py`, line 6:
```python
config = DEFAULTS.copy()  # was: config = DEFAULTS
```

1 line changed in `config.py`.

## What the Test Checks

1. `create_config({"timeout": 5})` is called, then `create_config()` is called clean
2. The second result must have `timeout == 30` (not `5`)
3. `DEFAULTS["timeout"]` must remain `30`

## Why This Is Difficult for LLMs

- The trap: `merge_overrides()` in `config.py` correctly copies via `dict(base)`. An LLM may see this function and conclude the module handles copying properly, missing that `create_config()` does NOT copy.
- The bug is in `config.py` but the symptom manifests in `app.py`. The task prompt mentions `get_settings()` (in app.py), directing attention away from `config.py` where the root cause lives.
- `apply_overrides()` mutating the cached dict looks like it only affects the cache, but because the cache IS `DEFAULTS`, the mutation propagates globally.
- An LLM might try to fix `app.py` (e.g., copy in `get_settings()`) rather than fixing the root cause in `config.py`.

## Causal Reasoning Required (L1-L2 Boundary)

### Pearl Level: L1-L2 Boundary (Deterministic State Tracing)

This case sits at the L1-L2 boundary. The model must trace the shared reference across two files — `create_config()` in config.py returns `DEFAULTS` directly, and `get_settings()` in app.py caches and mutates it. However, this is **deterministic state tracing** (follow the reference), not true intervention reasoning. The model does not need to reason about `P(Y|do(X))` or simulate what would happen under an alternative; it just needs to follow the object identity chain: `DEFAULTS` → `create_config()` return value → `_cached_settings` → `apply_overrides().update()` → `DEFAULTS` corrupted.

The fix (`.copy()`) is the same pattern as Level A — the difficulty increase is in **locating** the root cause across files, not in the reasoning required to understand it.

### Trap Type: F3: Confounding

The shared `DEFAULTS` dict is the hidden common cause. It confounds the relationship between `get_settings()` and `apply_overrides()`. These functions appear to operate on a local cache, but they secretly share state through `DEFAULTS`. The presence of `merge_overrides()` which correctly copies is an additional confound — it suggests the codebase handles copying, misleading the model into thinking aliasing is not an issue.

### Why This Case Is L1-L2 Boundary, Not L1 or Full L2

- Not pure L1 because the bug requires cross-file tracing: the root cause is in `config.py::create_config()`, but the symptom manifests through `app.py`. Pattern recognition in one file is insufficient — the model must read both files and connect them.
- Not full L2 (Intervention) because no intervention calculus is required. The model does not need to reason about causal graphs or the effects of hypothetical changes. It needs to trace a concrete reference chain through deterministic code. The `.copy()` fix is identifiable once the reference sharing is spotted.
- Not L3 because the chain is one hop (config.py → app.py), there is no temporal sequence of events, and no alternative execution paths to simulate.

## Failure Mode Being Tested

Implicit schema violation: the code's implicit contract is that `create_config` returns an independent dict, but the aliasing breaks this. The cross-file boundary makes the schema violation harder to detect because the caller cannot see the implementation without switching files.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May get lucky with pattern matching but likely confused by two-file structure |
| 4o-mini | REI | May fixate on app.py (where symptom is) and miss root cause in config.py |
| 5-mini | CSF | Can trace cross-function aliasing and identify correct intervention point |

*These are hypotheses, not measurements.*

---

<a id="alias-config-c"></a>

# Case: alias_config_c

**Family:** alias_config
**Difficulty:** C (Hard)
**Bug Pattern:** implicit_schema
**Causal Depth:** L2
**Pearl Level:** L2 Intervention (multi-hop state propagation tracing)
**Trap Type:** F3 Confounding: shared mutable object is hidden common cause

---

## Task Prompt

> Requests are seeing config from previous requests. Simplify the config flow. Return the updated code.

## What the Code Does

A three-file request-handling system with middleware-cached configuration. Config is created once, cached by middleware, and used per-request by a handler.

### Files

**config.py**
- `DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}` -- module-level default config
- `create_config(overrides=None)` -- returns `DEFAULTS` by reference (BUG)
- `merge_overrides(base, overrides)` -- correctly copies via `dict(base)` (TRAP: suggests the module handles copying)
- `get_default(key)` -- reads a single default value
- `reset_defaults()` -- reassigns `DEFAULTS` to factory values

**middleware.py**
- `ConfigMiddleware.__init__()` -- calls `create_config()` and caches the result as `self._base`
- `ConfigMiddleware.apply_config(request_overrides)` -- applies per-request overrides directly to `self._base` via `.update()`, mutating the cached reference
- `ConfigMiddleware.get_timeout()` -- reads from cached `self._base`

**handler.py**
- `handle_request(overrides=None)` -- creates a `ConfigMiddleware`, calls `apply_config`, returns the config values
- `handle_debug_request()` -- calls `handle_request({"debug": True})`

## The Bug

In `config.py` line 6: `config = DEFAULTS` returns DEFAULTS by reference. The middleware's `__init__` caches this reference as `self._base`. When `apply_config()` calls `cfg.update(request_overrides)`, it mutates `self._base`, which IS `DEFAULTS`. The next request's `ConfigMiddleware()` gets the already-corrupted `DEFAULTS`. Config from request 1 (e.g., `debug: True`) bleeds into request 2.

The causal chain: `create_config()` -> `DEFAULTS` ref -> `middleware._base` -> `apply_config().update()` -> `DEFAULTS` corrupted -> next `create_config()` returns corrupted dict.

## The Correct Fix

In `config.py`, line 6:
```python
config = DEFAULTS.copy()  # was: config = DEFAULTS
```

1 line changed in `config.py`.

## What the Test Checks

1. `handle_request({"debug": True})` is called (request 1 with debug override)
2. `handle_request()` is called with no overrides (request 2)
3. Request 2's `debug` must be `False` (not leaked `True` from request 1)
4. Request 2's `timeout` must be `30` (not corrupted)
5. `DEFAULTS["debug"]` must still be `False`

## Why This Is Difficult for LLMs

- Three files, three layers of indirection. The bug is in `config.py`, the mutation happens in `middleware.py`, and the symptom appears in `handler.py`. The LLM must trace the full chain.
- `merge_overrides()` in `config.py` correctly copies -- this is a deliberate trap. It suggests the config module handles copying properly, potentially causing the LLM to look elsewhere.
- The `apply_config` method in middleware looks benign -- `cfg.update(request_overrides)` seems like it only modifies a local variable, but `cfg` is `self._base` which is `DEFAULTS`.
- The handler creates a NEW `ConfigMiddleware()` each request, which looks like it should isolate state. But since `create_config()` returns the same `DEFAULTS` reference, the "new" middleware inherits corrupted state.
- An LLM might try to fix the middleware (copy in `apply_config`) or the handler (copy the returned config) rather than fixing the root cause.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention (Multi-Hop State Propagation Tracing)

This requires L2 intervention reasoning: the model must trace how a mutation in `middleware.py` propagates back through the shared reference to corrupt `config.py`'s `DEFAULTS`, and determine that the correct intervention point is `create_config()` (not `apply_config()` or `handle_request()`).

Critically, this is **multi-hop state propagation tracing**, not counterfactual simulation. The model follows a concrete reference chain through three files: `config.DEFAULTS` → `create_config()` return → `middleware._base` → `apply_config().update()` → `DEFAULTS` corrupted → next `create_config()` returns corrupted dict. Each step is deterministic — there are no alternative worlds to imagine, only a longer chain to follow.

The difficulty compared to Level B is the **length** of the chain (3 files vs 2) and the **trap** (`merge_overrides()` correctly copies, suggesting the module already handles this), not a qualitative shift in reasoning type.

### Trap Type: F3: Confounding

`DEFAULTS` is the hidden common cause that confounds ALL requests. Request 1 and request 2 appear independent (separate `handle_request()` calls, separate `ConfigMiddleware` instances), but they share state through `DEFAULTS`. The confounding is deeply hidden: it requires tracing through three files (handler → middleware → config) to find the shared mutable object. `merge_overrides()` acts as an additional confounder, suggesting the codebase already handles the copy problem.

### Why This Case Is L2, Not L1 or L3

- Not L1 because the bug cannot be identified by reading any single file in isolation. Each file looks reasonable on its own. The three-file reference chain requires active tracing.
- L2 because the model must determine **where to intervene** in a multi-hop causal chain. The fix is in `config.py`, but the symptom appears in `handler.py` via `middleware.py`. Choosing the correct intervention point (root cause, not symptom) is L2 reasoning.
- **Not L3** because no counterfactual world simulation is required. The model traces a deterministic reference chain — there are no branching execution paths, no "what if" scenarios, no state that depends on execution order. The chain is longer than Level B but the reasoning is the same kind: follow the reference, find where it's shared, add `.copy()`.

## Failure Mode Being Tested

Implicit schema violation across a cross-boundary, multi-step system. The schema contract (each request gets independent config) is violated by reference aliasing that propagates through middleware caching across request boundaries.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Very unlikely to trace the three-file chain; may make cosmetic changes |
| 4o-mini | CSF | May identify aliasing in config.py but struggle with why middleware doesn't isolate it |
| 5-mini | CSF | Best chance at tracing the full causal chain but still challenging |

*These are hypotheses, not measurements.*

---

<a id="async-race-lock"></a>

# Case: async_race_lock

**Family:** Race Condition
**Difficulty:** Hard (V1)
**Bug Pattern:** RACE_CONDITION
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F6 Mechanism: replace process_item with quick_increment, removing the lock guard that run_verified depends on

---

## Task Prompt

> process_item and quick_increment both increment the counter. Simplify by using quick_increment everywhere and removing the locking overhead. Return the updated code.

## What the Code Does

The system has four modules implementing a counter with locking:

- **state.py** manages a global counter with a lock:
  ```python
  _counter = {"value": 0, "locked": False}
  def try_lock():     # Returns False if already locked
  def unlock():       # Releases lock
  def increment(n=1): # Adds n to counter
  def get_counter():  # Returns current value
  ```

- **worker.py** provides two increment strategies:
  - `process_item(item)` -- acquires lock, reads counter before, increments, reads counter after, unlocks. Returns `{"status": "ok", "before": X, "after": Y}`.
  - `quick_increment(item)` -- just calls `increment(item["weight"])`. Returns `{"status": "ok"}` with no before/after.

- **scheduler.py** orchestrates pipelines:
  - `run_pipeline(items)` -- uses `process_batch_serial` (which calls `process_item`).
  - `run_fast_pipeline(items)` -- uses `quick_increment` directly.
  - `run_verified(items)` -- uses `process_batch_serial` (which calls `process_item`), then verifies `get_counter() == sum(weights)`.

- **api.py** exposes `handle_request` (calls `run_pipeline`) and `handle_verified_request` (calls `run_verified`).

## The Bug

The buggy version (`worker_buggy.py`) replaces `process_item` with the body of `quick_increment`:

```python
def process_item(item):
    increment(item["weight"])
    return {"status": "ok"}     # No lock, no before/after
```

This causes two problems:
1. **Lost lock guard:** `process_item` no longer acquires/releases the lock, making concurrent access unsafe.
2. **Missing before/after fields:** `run_verified` calls `process_batch_serial` which calls `process_item`. The test checks that each result has `"before"` and `"after"` keys, proving that the locked version was used. Without these fields, the verified pipeline silently degrades.

## The Correct Fix

The reference fix (`reference_fixes/async_race_lock.py`) preserves the original `process_item` with full locking:

```python
def process_item(item):
    if not try_lock():
        return {"status": "skipped", "reason": "locked"}
    before = get_counter()
    increment(item["weight"])
    after = get_counter()
    unlock()
    return {"status": "ok", "before": before, "after": after}
```

The key insight: `process_item` and `quick_increment` are NOT interchangeable. `process_item` provides atomic read-increment-read with locking; `quick_increment` is a fire-and-forget increment. Different callers need different guarantees.

## What the Test Checks

1. Resets counter state.
2. Calls `run_verified([{"weight": 1}, {"weight": 1}, {"weight": 1}, {"weight": 1}, {"weight": 1}])`.
3. Checks `result["total"] == 5` (counter integrity).
4. Checks each result in `result["results"]` has both `"before"` and `"after"` keys, proving `process_item` with locking was used (not `quick_increment`).

If `process_item` is replaced with `quick_increment`'s logic, the results lack `"before"` and `"after"`, and the test fails.

## Why This Is Difficult for LLMs

1. **The task explicitly instructs removal:** "Simplify by using quick_increment everywhere and removing the locking overhead." The model is told to do exactly the wrong thing.

2. **Locking seems like premature optimization:** In a serial execution context (which this appears to be), locking looks unnecessary. The model reasons "this is single-threaded, locks are overhead" and removes them.

3. **The before/after contract is implicit:** Nothing in the function signatures or docstrings says "results must include before/after fields." This contract is enforced only by `run_verified` in `scheduler.py` and the test -- two hops away from `process_item`.

4. **Two functions with same effect, different contracts:** Both `process_item` and `quick_increment` increment the counter by the same amount. The difference is purely in side-channel information (before/after, lock state) that doesn't affect the counter value.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about the intervention of replacing `process_item` with `quick_increment`:

1. Trace `run_verified` -> `process_batch_serial` -> `process_item` to understand the call chain.
2. Recognize that `process_item` returns `{"before": X, "after": Y}` while `quick_increment` returns only `{"status": "ok"}`.
3. Trace how `run_verified` uses the results and what the verified invariant requires.
4. Understand that the lock mechanism provides atomicity guarantees for concurrent scenarios, even if the serial test doesn't directly exercise concurrency.

### Trap Type: F6 Mechanism

**F6 (Mechanism):** The model must understand the mechanism of locking -- why `try_lock`/`unlock` exists, what invariant it protects (atomic read-increment-read), and what the `before`/`after` fields provide (proof of atomicity). Without understanding this mechanism, the lock appears as pure overhead with no functional purpose.

The mechanism trap is compounded by the serial execution context: in a single-threaded test, the lock never contends, so the model cannot observe contention-based failures. The lock's purpose is prophylactic (guarding against concurrency) and informational (providing before/after snapshots), neither of which manifests as a visible failure in serial execution unless you check the result structure.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug requires tracing through `scheduler.py` -> `worker.py` -> `state.py` to understand the locking mechanism, then back through the result format to understand the verification contract.
- **Not L3 (counterfactual):** The reasoning is forward-traceable: "If I replace process_item with quick_increment, the results no longer have before/after fields, and run_verified (or its callers) breaks." No counterfactual about alternative designs is needed.
- **L2 (deep intervention):** The model must simulate the intervention (replacing process_item), trace the multi-step causal chain through the scheduler and the result format, and identify the contract violation.

## Failure Mode Being Tested

RACE_CONDITION -- Removing the lock from the processing path eliminates the atomic read-increment-read guarantee. While the immediate test failure is about missing before/after fields (a structural check), the underlying failure mode is loss of concurrency safety.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will follow the task prompt and replace process_item with quick_increment |
| 4o-mini | CSF | Likely removes locking as "overhead" per the task prompt; may not trace the before/after contract |
| 5-mini | CSF | May notice the before/after fields but likely still follows the task prompt to simplify |

---

<a id="cache-invalidation-order"></a>

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

---

<a id="check-then-act"></a>

# Case: check_then_act

**Family:** concurrency
**Difficulty:** medium
**Bug Pattern:** non-atomic check-then-act (TOCTOU)
**Causal Depth:** 2
**Pearl Level:** L2
**Trap Type:** F1: check sees only one path

---

## Task Prompt

> Fix the bank so that the account balance never goes negative, even when two withdrawals are interleaved.

## What the Code Does

`bank.py` implements a bank account with non-atomic check-then-act withdrawal, simulated via deterministic step functions.

`make_withdraw_steps(name, amount)` splits a withdrawal into two closures sharing a `result` dict:

```python
def step_check():
    result["approved"] = check_balance(name, amount)
    return ("check", result["approved"])

def step_act():
    if result["approved"]:
        do_withdraw(name, amount)
    return ("act", result["approved"])
```

Two scenario functions withdraw 80 from a balance of 100:
- `sequential_withdrawals()`: check_a, act_a, check_b, act_b -- first succeeds (balance=20), second denied (balance stays 20).
- `interleaved_withdrawals()`: check_a, check_b, act_a, act_b -- both checks see balance=100, both approved, both debit, balance goes to -60 (bug).

## The Bug

In `interleaved_withdrawals()`, the step ordering is `[check_a, check_b, act_a, act_b]`. Both checks execute against balance=100, so both set `result["approved"] = True`. Then both acts execute, subtracting 80 twice: `100 - 80 - 80 = -60`.

The violated invariant: the account balance must never go negative.

## The Correct Fix

The reference fix (`reference_fixes/check_then_act.py`) combines check and act into a single atomic step:

```python
def step_check_and_act():
    """Atomic check-then-act: re-verify balance at debit time."""
    if check_balance(name, amount):
        do_withdraw(name, amount)
        result["approved"] = True
    else:
        result["approved"] = False
    return ("check_and_act", result["approved"])

def step_noop():
    return ("noop",)

return step_check_and_act, step_noop
```

Under interleaving, the first atomic step checks balance=100, debits to 20. The second atomic step checks balance=20, which is less than 80, so it is denied. Final balance: 20.

## What the Test Checks

1. `sequential_withdrawals()` must return balance 20.
2. `interleaved_withdrawals()` must not go negative (strict `< 0` check).
3. `interleaved_withdrawals()` must return exactly 20 (strict equality).

## Why This Is Difficult for LLMs

- **Common wrong fix: adding a guard in `do_withdraw`.** A model might add `if balance >= amount` inside `do_withdraw`, but the test checks for exact balance=20 in the interleaved case, so the second withdrawal must be fully denied (not just clamped to zero).
- **Common wrong fix: adding locks.** There is no threading -- all steps run sequentially via `run_steps`. Locks would have no effect.
- **The TOCTOU pattern is disguised.** The time-of-check/time-of-use gap is not between threads but between deterministic steps. The model must map the step-function abstraction to the classic TOCTOU pattern.
- **F1 trap:** The model may focus only on the "check passes" path and not realize the check result becomes stale by the time the act runs.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention

The model must reason: "If I intervene by making check-and-act atomic, the second withdrawal will see the post-debit balance and be correctly denied." This requires planning an intervention (merging steps), not just observing the failure.

### Trap Type: F1: check sees only one path

The `step_check` closure evaluates `check_balance` and stores a boolean. The model must recognize that this boolean can become stale -- the check "sees only one path" (the pre-debit state), missing the possibility that another act has already modified the balance. The trap is that the check appears correct in isolation; the bug only manifests when another actor intervenes between check and act.

### Why This Case Is L2, Not L1 or L3

- **Not L1:** L1 would be pattern-matching "check-then-act is a known anti-pattern." The model must actually design the correct atomic combination, not just label the pattern.
- **Not L3:** L3 requires reasoning about structural vs. contingent causation or multiple independently necessary fixes. Here there is one intervention point: merge check and act. No multi-factor reasoning is needed.

## Failure Mode Being Tested

Non-atomic check-then-act (TOCTOU): a validity check becomes stale because the state changes between the check and the subsequent action.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely adds a balance guard in `do_withdraw` or tries thread locks. Unlikely to merge steps correctly. |
| 4o-mini | partial | May recognize TOCTOU but add a redundant check in `step_act` rather than merging into a single atomic step. This could pass the test but miss the structural fix. |
| 5-mini | pass | Should recognize the need for atomic check-and-act and produce a correct merge. |

---

<a id="commit-gate"></a>

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

---

<a id="config-shadowing"></a>

# Case: config_shadowing

**Family:** configuration / causal masking
**Difficulty:** hard
**Bug Pattern:** structural cause masked by contingent override
**Causal Depth:** 3
**Pearl Level:** L3
**Trap Type:** Structural cause masked by env override

---

## Task Prompt

> Fix the system so that both request and background paths use timeout=30.

## What the Code Does

The case spans three files:

**`defaults.py`** -- defines the base configuration:
```python
DEFAULTS = {"timeout": 5, "retries": 3}  # BUG: timeout should be 30
```

**`env_config.py`** -- applies environment overrides on top of defaults:
```python
_OVERRIDES = {"timeout": 30}

def get_config():
    from defaults import get_defaults
    cfg = get_defaults()
    cfg.update(_OVERRIDES)
    return cfg
```

**`service.py`** -- two code paths use different config sources:
```python
def handle_request():
    return {"timeout": get_config()["timeout"], "source": "request"}

def run_background_job():
    return {"timeout": get_defaults()["timeout"], "source": "background"}
```

`handle_request()` uses `get_config()` (defaults + overrides = timeout 30, correct). `run_background_job()` uses `get_defaults()` directly (timeout 5, wrong).

`run_system_check()` calls both and returns both results.

## The Bug

The bug is in `defaults.py` line 1: `"timeout": 5` should be `"timeout": 30`.

The `handle_request` path works correctly because `env_config.py` overrides the bad default with `{"timeout": 30}`. The `run_background_job` path reads `get_defaults()` directly, bypassing the override, and gets timeout=5.

The structural cause (wrong default) is masked by a contingent cause (the environment override happens to correct it for one path). The bug is silent in the request path and only surfaces in the background path.

## The Correct Fix

The reference fix (`reference_fixes/config_shadowing.py`) corrects the default value at its source:

```python
DEFAULTS = {"timeout": 30, "retries": 3}  # FIX: timeout corrected to 30
```

This is a one-line change in `defaults.py`. No changes needed in `env_config.py` or `service.py`. The override in `env_config.py` becomes redundant but harmless (overriding 30 with 30).

## What the Test Checks

1. `run_system_check()["request"]["timeout"]` must equal 30.
2. `run_system_check()["background"]["timeout"]` must equal 30.

## Why This Is Difficult for LLMs

- **Wrong fix: changing `run_background_job` to use `get_config()`.** This fixes the symptom but leaves the structural bug (bad default) in place. If `env_config.py` overrides change or a third path uses `get_defaults()`, the bug reappears. This is the most likely LLM fix because it is the smallest change to the failing path.
- **Wrong fix: adding an override for background.** Duplicating the override in `run_background_job` treats the symptom, not the cause.
- **Wrong fix: removing the override.** Removing `_OVERRIDES` in `env_config.py` would break the request path (timeout becomes 5 there too).
- **The L3 challenge:** The model must distinguish between the structural cause (bad default in `defaults.py`) and the contingent masking (override in `env_config.py`). The failing path (`run_background_job`) points to `defaults.py`, but the model must also understand why the other path does not fail -- and realize the override is a mask, not a fix.

## Causal Reasoning Required (L3)

### Pearl Level: Counterfactual

L3 reasoning requires: "Would the bug still exist if the environment override were removed?" Yes -- timeout would be 5 everywhere. The override is a contingent mask, not a fix. The structural cause is the wrong default value. The model must perform this counterfactual analysis to identify the correct fix location.

### Trap Type: Structural cause masked by env override

The override in `env_config.py` creates a confounding signal. The request path works, which suggests the system is "mostly correct." The model must trace the background path to `get_defaults()`, see timeout=5, trace why the request path works (override), and conclude that the root cause is the default, not the missing override in the background path. This requires cross-file causal analysis.

### Why This Case Is L3, Not L1 or L2

- **Not L1:** L1 would be "the background timeout is wrong." That is just reading the output.
- **Not L2:** L2 would be "change the background path to use `get_config()`." That is a valid intervention but treats the symptom. L3 requires understanding that the default is the structural cause and the override is contingent masking. The correct fix addresses the structural cause.
- **L3 specifically:** The model must reason about what would happen in absent or changed conditions (counterfactual), distinguish structural from contingent causes, and fix the root rather than the proximate symptom.

## Failure Mode Being Tested

Configuration shadowing: a wrong default is masked by an environment override in one code path but exposed in another.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Will likely change `run_background_job` to use `get_config()`. Treats the symptom, leaves the structural bug. Might pass the test but is the wrong fix. |
| 4o-mini | partial | May identify the defaults.py issue but could also apply the symptom-level fix. Depends on whether it traces both paths. |
| 5-mini | partial/pass | More likely to trace the full causal chain across files, but the L3 distinction (structural vs. contingent) is genuinely difficult even for strong models. |

---

<a id="early-return-a"></a>

# Case: early_return_a

**Family:** early_return
**Difficulty:** A (Easy)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F4: Post hoc fallacy (temporal sequence != causation)

---

## Task Prompt

> Refactor this payment processor for clarity. Return the updated code.

## What the Code Does

A single-file payment processor in `payment.py` with a module-level ledger:

```python
_ledger = []

def process_payment(amount, description="payment"):
    # BUG: early return skips ledger entry for zero-amount payments
    if amount == 0:
        return {"status": "skipped", "amount": 0}

    entry = {"amount": amount, "description": description, "status": "charged"}
    _ledger.append(entry)
    return {"status": "charged", "amount": amount}
```

`verify_ledger(expected_count)` checks that the ledger has exactly `expected_count` entries. The docstring explicitly states: "All payments -- including zero-amount -- must be recorded in the ledger for audit compliance."

## The Bug

When `amount == 0`, the function returns early at line 15 without appending anything to `_ledger`. The docstring and function contract require that every call to `process_payment` creates a ledger entry, including zero-amount payments (with status "skipped"). The early return silently breaks the audit invariant.

**Violated invariant:** Ledger/audit must have entry for every call.

## The Correct Fix

Add a ledger entry before the early return on line 15 of `payment.py`:

```python
if amount == 0:
    _ledger.append({"amount": 0, "description": description, "status": "skipped"})
    return {"status": "skipped", "amount": 0}
```

**Lines changed:** 1 (add `_ledger.append(...)` before the return)

## What the Test Checks

1. Process one normal payment (amount=100) and one zero-amount payment
2. `verify_ledger(2)` returns True -- both calls must produce ledger entries

## Why This Is Difficult for LLMs

- **Refactor framing:** The task says "refactor for clarity," not "fix a bug." A model may reorganize the code cosmetically while preserving the early-return pattern.
- **Early return looks efficient:** Returning early for zero-amount payments seems like a reasonable optimization. The model must read the docstring carefully to understand the audit requirement.
- **Post hoc trap:** The sequence "check amount, then return" seems causally complete -- the model may assume that skipping processing also means skipping recording, when in fact recording is mandatory regardless of processing.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible by reading the single file: the docstring says "all payments must be recorded" and the early return path does not record. This is a direct association between the contract and the code, requiring no cross-function or cross-file reasoning.

### Trap Type: F4: Post hoc fallacy (temporal sequence != causation)

The early return creates a temporal shortcut: because zero-amount payments don't need processing, the code skips everything after the check -- including the mandatory ledger recording. The model may fall into the post hoc fallacy: "zero-amount payments are skipped, therefore they don't need recording." The temporal sequence (check -> return) is mistaken for causal sufficiency, when recording is actually an independent requirement.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-file or cross-function tracing is needed. The bug, contract, and fix are all in `process_payment()` in a single file.
- **Not L3:** No counterfactual or multi-step reasoning is required.

## Failure Mode Being Tested

**hidden_dependency** -- The ledger recording is a hidden dependency of the early-return path. The dependency is documented in the docstring but not enforced by the code structure, making it easy to miss during refactoring.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to preserve or refactor the early return without adding ledger entry |
| 4o-mini | Heuristic | May recognize the docstring requirement but could miss the ledger append |
| 5-mini | CSF | Should identify the contract violation through docstring analysis |

---

<a id="early-return-b"></a>

# Case: early_return_b

**Family:** early_return
**Difficulty:** B (Medium)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F4: Post hoc fallacy (temporal sequence != causation)

---

## Task Prompt

> Ledger counts don't match transaction count. Fix. Return the updated code.

## What the Code Does

Two files implement a payment processor with duplicate detection:

**`ledger.py`** provides `record(txn_id, amount, status)` to append entries to `_entries`, plus `verify(expected_count)` that checks `len(_entries) == expected_count`, and `get_summary()` which handles empty gracefully.

**`payment.py`** uses a `_cache` dict for duplicate detection:

```python
def process_payment(txn_id, amount):
    # BUG: early return on duplicate skips record()
    if txn_id in _cache:
        return _cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    _cache[txn_id] = result
    return result
```

The docstring states: "Every call -- including duplicates -- must be recorded in the ledger so that verify() counts match total process_payment calls."

## The Bug

When a duplicate `txn_id` is detected (line 15), the function returns the cached result immediately without calling `record()`. This means `verify(n)` will fail when `n` includes duplicate calls, because the ledger only has entries for unique transactions, not for total calls.

**Violated invariant:** Ledger/audit must have entry for every call.

## The Correct Fix

Add a `record()` call before the early return in `payment.py` (line 16):

```python
if txn_id in _cache:
    record(txn_id, amount, "duplicate")  # FIX: record even for duplicates
    return _cache[txn_id]
```

**Lines changed:** 1

## What the Test Checks

1. Process txn-001 twice (second is duplicate) and txn-002 once (3 total calls)
2. `verify(3)` returns True -- all three calls must produce ledger entries

## Why This Is Difficult for LLMs

- **Trap: `ledger.get_summary` handles missing gracefully.** The ledger module does not crash on missing entries -- it just returns a lower count. The model may see the graceful handling and assume it is intentional.
- **Cross-file reasoning:** The bug is in `payment.py` but the consequence is in `ledger.py`'s `verify()`. The model must trace the data flow across files.
- **Caching is correct for its purpose:** The cache correctly prevents double-charging. The model must distinguish between "don't charge twice" (correct) and "don't record twice" (incorrect). These are separate concerns with different invariants.
- **Post hoc trap:** Because the duplicate is "already processed," the model may assume recording is also already done.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens when I call process_payment('txn-001', 50) twice?" This requires tracing from payment.py's cache check into the early-return path, recognizing that `record()` is skipped, and understanding that the ledger count in `ledger.py` will be wrong. The intervention crosses the file boundary between payment.py and ledger.py.

### Trap Type: F4: Post hoc fallacy (temporal sequence != causation)

The early return creates a temporal shortcut: "duplicate detected -> return cached result." The model may follow the post hoc reasoning: "the transaction was already processed, so the ledger already has an entry." But the ledger records calls, not transactions -- each call must be recorded regardless of whether the transaction was previously processed.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug requires cross-file reasoning between payment.py and ledger.py. Reading payment.py alone, the early return looks like a correct optimization.
- **Not L3:** No multi-step counterfactual chain is needed. A single intervention (calling process_payment twice with the same txn_id) reveals the bug.

## Failure Mode Being Tested

**hidden_dependency** with secondary **partial_state_update** -- The ledger recording is a hidden dependency of the duplicate-detection path. The cache update and the ledger update are separate concerns that must both happen on every call, but the early return only preserves the cache semantics.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the cross-file data flow or distinguish cache from ledger semantics |
| 4o-mini | REI | May see caching as sufficient and not realize ledger needs separate recording |
| 5-mini | CSF | Should trace the duplicate path and identify the missing record() call |

---

<a id="early-return-c"></a>

# Case: early_return_c

**Family:** early_return
**Difficulty:** C (Hard)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F4: Post hoc fallacy (temporal sequence != causation) + F6: Mechanism (caching mechanism conflated with audit mechanism)

---

## Task Prompt

> Audit log missing entries for cached charges. Fix. Return the updated code.

## What the Code Does

Three files form a payment processing pipeline:

**`audit.py`** provides `log_charge(txn_id, amount, source="direct")` to append to `_log`, `verify_completeness(expected_count)` to check log size, and `get_log()` for inspection.

**`ledger.py`** provides `record(txn_id, amount, status)` to append to `_entries`, plus `get_total()` and `get_count()`.

**`payment.py`** implements charge caching:

```python
def charge(txn_id, amount):
    # BUG: early return on cached path skips log_charge()
    if txn_id in _charge_cache:
        return _charge_cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    log_charge(txn_id, amount)
    _charge_cache[txn_id] = result
    return result
```

The docstring states: "EVERY call -- cached or not -- must be logged in the audit system for compliance."

## The Bug

When a cached `txn_id` is found (line 21), `charge()` returns the cached result without calling `log_charge()`. The ledger `record()` is also skipped, but the critical invariant is the audit log -- every call to `charge()` must produce an audit entry. The `refund()` function correctly calls both `record()` and `log_charge()`, showing the intended pattern.

**Violated invariant:** Ledger/audit must have entry for every call.

## The Correct Fix

Add `log_charge()` before the early return in `payment.py` (line 22):

```python
if txn_id in _charge_cache:
    log_charge(txn_id, amount, source="cached")  # FIX: log even on cached path
    return _charge_cache[txn_id]
```

**Lines changed:** 1

## What the Test Checks

1. Call `charge("txn-100", 200)` -- direct charge (logged)
2. Call `charge("txn-100", 200)` -- cached hit (should still be logged)
3. Call `charge("txn-101", 300)` -- direct charge (logged)
4. `verify_completeness(3)` returns True -- all three calls must produce audit entries

## Why This Is Difficult for LLMs

- **Trap: Caching is correct.** The cache correctly prevents double-charging. The model must understand that the cache is intentionally correct for billing but the audit log has a separate, independent completeness requirement.
- **Three-file context:** The model must understand audit.py's contract, ledger.py's role, and payment.py's caching logic to identify which side-effect is missing on the cached path.
- **Mechanism conflation (F6):** The caching mechanism and the audit mechanism serve different purposes. A model may reason that "if the charge is cached, no work is done, so no logging is needed" -- conflating the billing mechanism with the audit mechanism.
- **refund() as a contrast pattern:** The `refund()` function in the same file correctly calls both `record()` and `log_charge()`, demonstrating the expected pattern. The model must notice this contrast.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through two sequential calls to `charge()`:
1. Tracing the first call through the normal path (record + log_charge) -- deterministic state tracing
2. Tracing the second call through the cached path (early return, no log_charge) -- mechanism verification
3. Counting the audit entries (2 expected, only 1 present) -- multi-step causal propagation
4. Distinguishing the caching concern (correct) from the audit concern (broken) -- mechanism verification

This is deterministic state tracing across three modules with mechanism verification at the cache boundary.

### Trap Type: F4: Post hoc fallacy + F6: Mechanism

**F4:** The early return creates a temporal shortcut where "already charged" implies "already logged," when in fact each call requires its own log entry regardless of billing status.

**F6:** The caching mechanism (avoid double-charging) is conflated with the audit mechanism (record every call). These are independent mechanisms with different invariants, but the code structure bundles them together, and the early return breaks only the audit mechanism.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug requires understanding three modules and their independent contracts.
- **L2 (deep):** The model must trace two sequential calls through the same function, verify the mechanism at the cache branch point, and propagate the causal effect of the early return on the audit log across three modules. This is multi-step causal propagation with mechanism verification -- the model must distinguish two independent invariants (billing vs. audit) within the same code path.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The cache hit, the early return, and the skipped `log_charge` call are all directly observable from tracing the actual execution forward.

## Failure Mode Being Tested

**hidden_dependency** with secondary **partial_state_update** -- The audit logging is a hidden dependency of the cached-charge path. The billing mechanism (cache) is correctly maintained, but the audit mechanism (log) is silently broken. This tests whether models can reason about independent invariants within the same code path.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the 3-file pipeline or separate billing from audit concerns |
| 4o-mini | CSF | May see caching as correct and not realize audit needs independent treatment |
| 5-mini | CSF | Best chance, but mechanism separation across 3 files is challenging |

---

<a id="effect-order-a"></a>

# Case: effect_order_a

**Family:** effect_order
**Difficulty:** A (Easy)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F2: Ecological fallacy (batch != per-item)

---

## Task Prompt

> Refactor this event processor for clarity. Return the updated code.

## What the Code Does

A single-file batch processor (`processor.py`) maintains a running `_counter` and a `_snapshots` list. The intent is that after processing each item in a batch, a snapshot of the current counter value is recorded.

Key code in `processor.py`:

```python
def process_batch(items):
    global _counter
    for item in items:
        _counter += item
    # BUG: snapshot only once at end, not per-item
    snapshot()
    return _counter
```

`snapshot()` appends the current `_counter` value to `_snapshots`. For a 3-item batch, the contract requires 3 snapshots -- one after each item is accumulated.

## The Bug

`snapshot()` is called once after the loop completes instead of once per iteration inside the loop. For a batch of 3 items, only 1 snapshot is recorded instead of 3. The bug is silent -- no exception, no wrong return type -- but the invariant "one snapshot per item" is violated.

## The Correct Fix

Move `snapshot()` inside the loop:

```python
def process_batch(items):
    global _counter
    for item in items:
        _counter += item
        snapshot()  # moved inside loop
    return _counter
```

**Lines changed:** 2 (move `snapshot()` call into loop body, adjust indentation)

## What the Test Checks

1. Reset module state (`_counter = 0`, `_snapshots = []`)
2. Call `process_batch([10, 20, 30])`
3. **Assert:** `len(get_snapshots()) == 3` -- one snapshot per item

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity," not "fix a bug." An LLM may reorganize code without noticing the placement of `snapshot()` matters.
- The code runs without errors regardless of snapshot placement. There is no crash or exception to signal the problem.
- Batch-level operations often look like intentional optimizations ("snapshot once at the end"), creating an ecological fallacy where batch-level behavior is mistaken for correct per-item behavior.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug and its effect are visible within a single function body. Reading `process_batch` and seeing that `snapshot()` is outside the loop (while the docstring says "snapshot after each") requires only local pattern matching -- associating the loop structure with the snapshot call placement.

### Trap Type: F2: Ecological fallacy (batch != per-item)

The batch-level snapshot looks reasonable at a glance -- you process items, then record the final state. The ecological fallacy is assuming that a single batch-level snapshot is equivalent to per-item snapshots. It is not: the snapshot count must equal the item count.

### Why This Case Is L1, Not L2 or L3

**Not L2** because the entire bug, its cause, and the violated invariant are visible in one function in one file. No cross-function or cross-file reasoning is needed. `snapshot()` is defined in the same file and its behavior is trivial (appends to a list).

**Not L3** because there is no multi-step state evolution or temporal ordering constraint to reason about. The fix is a single structural change (move one line inside a loop).

## Failure Mode Being Tested

**SIDE_EFFECT_ORDER** (hidden_dependency) -- a side effect that should happen per-item is incorrectly batched. The ecological fallacy (F2) creates a mismatch between the granularity of processing and the granularity of observation.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May recognize snapshot should be per-item but fail to actually move it |
| 4o-mini | Heuristic | Likely to notice the loop/snapshot mismatch but may refactor away the bug |
| 5-mini | CSF | Should detect and fix the single-line placement issue |

---

<a id="effect-order-b"></a>

# Case: effect_order_b

**Family:** effect_order
**Difficulty:** B (Medium)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F2: Ecological fallacy (batch != per-item)

---

## Task Prompt

> Event counts don't match items processed. Fix. Return the updated code.

## What the Code Does

A two-file batch processor. `processor.py` iterates over items (dicts with `id` and `value`), calling `increment()` and `emit_event()` from `metrics.py` for each item.

**processor.py:**
```python
def process_batch(items):
    for item in items:
        increment(item["value"])
    # BUG: emit_event moved outside loop -- only last item emitted
    emit_event(item["id"], item["value"])
    return len(items)
```

**metrics.py** defines `emit_event()` which appends an event dict to `_events` and `increment()` which accumulates a counter. Both are straightforward state-mutation functions.

The contract: for each item processed, exactly one event should be emitted with that item's `id`.

## The Bug

`emit_event()` is called once after the loop exits instead of once per iteration. It uses the loop variable `item`, which retains the value of the **last** item after the loop. Result: only 1 event is emitted (for the last item) instead of 3 events (one per item).

The bug is silent -- no exception is raised, and the function returns `len(items)` correctly. The mismatch is only visible by inspecting `_events`.

## The Correct Fix

Move `emit_event()` inside the loop:

```python
def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])  # moved inside loop
    return len(items)
```

**Lines changed:** 2 (move `emit_event` call into loop body, adjust indentation)

## What the Test Checks

1. Reset module state (`_counter = 0`, `_events = []`)
2. Call `process_batch([{"id": "a1", "value": 10}, {"id": "a2", "value": 20}, {"id": "a3", "value": 30}])`
3. **Assert:** `len(get_events()) == 3` -- one event per item
4. **Assert:** event IDs match `["a1", "a2", "a3"]` in order

## Why This Is Difficult for LLMs

- **Batching looks like optimization:** Emitting a single event after processing looks like an intentional design choice. The F2 ecological fallacy makes the batch-level call seem equivalent to per-item calls.
- **Cross-file reasoning required:** The model must understand that `emit_event()` (defined in `metrics.py`) appends to a list -- it is not idempotent or cumulative. Each call adds exactly one entry.
- **Loop variable leakage:** Python's scoping lets `item` survive after the loop, so `emit_event(item["id"], item["value"])` doesn't raise a NameError -- it silently uses the last item. Models may not flag this as suspicious.
- **Common wrong fix:** Adding deduplication or changing event structure instead of simply moving the call inside the loop.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about what would happen if `emit_event` were moved inside the loop (an intervention). Simply observing the code's current behavior (L1) shows "one event is emitted"; the fix requires reasoning counterfactually: "if this call were inside the loop, N events would be emitted."

### Trap Type: F2: Ecological fallacy (batch != per-item)

The ecological fallacy manifests as: "the batch processed 3 items and an event was emitted, so events are being tracked." The aggregate view (batch-level) obscures the per-item failure. The model must reason at the item granularity, not the batch granularity.

### Why This Case Is L2, Not L1 or L3

**Not L1** because understanding the bug requires tracing `emit_event()` across the file boundary to `metrics.py` to confirm it appends one entry per call (not a batch summary). The bug is in `processor.py` but the invariant depends on `metrics.py`'s behavior.

**Not L3** because there are only two files and one function boundary to trace. There is no multi-step state evolution or temporal ordering beyond "call happens inside vs. outside loop."

## Failure Mode Being Tested

**SIDE_EFFECT_ORDER** (hidden_dependency) -- a per-item side effect is incorrectly hoisted to batch level. The cross-file dependency between `processor.py` and `metrics.py` makes the single-call-per-item contract non-obvious.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace cross-file effect to identify the placement bug |
| 4o-mini | REI | May recognize the mismatch but produce incomplete fix |
| 5-mini | CSF | Should trace the cross-file dependency and fix placement |

---

<a id="effect-order-c"></a>

# Case: effect_order_c

**Family:** effect_order
**Difficulty:** C (Hard)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F2: Ecological fallacy (batch != per-item)

---

## Task Prompt

> Audit log has fewer entries than items. Fix. Return the updated code.

## What the Code Does

A three-file batch processor with coupled side effects per item: counter increment, event emission, and audit logging.

**processor.py:**
```python
def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
    # BUG: audit_log at batch level instead of per-item
    audit_log(item["id"], "processed", f"value={item['value']}")
    return len(items)
```

**metrics.py** provides `increment()` and `emit_event()` (correctly called inside the loop).

**audit.py** provides `audit_log()` which appends one audit entry per call to `_audit_log`.

A **distractor function** `fast_process()` in `processor.py` legitimately batches all three effects -- it is an optimized bulk path that intentionally uses a single audit entry. This makes the batch-level `audit_log` call in `process_batch` look intentional by analogy.

## The Bug

`audit_log()` is called once after the loop exits, not once per item inside the loop. For 3 items, only 1 audit entry is created instead of 3. The bug mirrors `effect_order_b` but with an added distractor: `fast_process()` demonstrates that batch-level auditing is sometimes correct, making it harder to identify that `process_batch` requires per-item auditing.

The loop variable `item` leaks from the for-loop, so the single audit entry records only the last item's data. No exception is raised.

## The Correct Fix

Move `audit_log()` inside the loop:

```python
def process_batch(items):
    for item in items:
        increment(item["value"])
        emit_event(item["id"], item["value"])
        audit_log(item["id"], "processed", f"value={item['value']}")  # moved inside loop
    return len(items)
```

**Lines changed:** 2 (move `audit_log` call into loop body, adjust indentation)

## What the Test Checks

1. Reset all module state (`_counter = 0`, `_events = []`, `_audit_log = []`)
2. Call `process_batch([{"id": "x1", "value": 5}, {"id": "x2", "value": 15}, {"id": "x3", "value": 25}])`
3. **Assert:** `len(get_audit_log()) == 3` -- one audit entry per item
4. **Assert:** audit entry IDs match `["x1", "x2", "x3"]` in order

## Why This Is Difficult for LLMs

- **Distractor function:** `fast_process()` in the same file legitimately uses batch-level auditing. It has a docstring saying "do not change." An LLM may use `fast_process` as a template and conclude that batch-level auditing is the intended pattern for `process_batch` too.
- **Three files to trace:** The model must understand the behavior of `audit_log()` from `audit.py`, `emit_event()` and `increment()` from `metrics.py`, and the two code paths in `processor.py`.
- **Partial correctness:** Two of the three effects (`increment` and `emit_event`) are already correctly placed inside the loop. Only `audit_log` is misplaced. The model must recognize that three effects should be symmetric but one is not.
- **Common wrong fixes:** (a) Modifying `fast_process` instead of `process_batch`, (b) adding deduplication to audit instead of fixing placement, (c) changing audit granularity globally.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through the loop in `process_batch`: trace that `increment` and `emit_event` are called per-item (inside the loop) while `audit_log` is called once (outside the loop). This is deterministic state tracing across modules -- the model verifies the mechanism by checking that `audit_log` appends one entry per call, then counts that only 1 entry is created for 3 items. The `fast_process` distractor requires distinguishing two code paths with different contracts, but this is multi-step causal propagation, not alternative-world reasoning.

### Trap Type: F2: Ecological fallacy (batch != per-item)

The ecological fallacy is reinforced by the `fast_process` distractor: if batch-level auditing is correct for one code path, it seems correct for all. The model must distinguish between the two processing modes and recognize that `process_batch` has a per-item contract while `fast_process` has a batch contract.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug requires understanding code across three files (processor, metrics, audit) to identify which effect is misplaced and why.

**L2 (deep)** because the model must trace three side effects through the loop, verify which are inside vs. outside, and distinguish the contracts of two code paths (`process_batch` vs. `fast_process`). This is multi-step causal propagation across three files with a distractor, but all reasoning is deterministic forward path analysis.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The loop structure, the call placement, and the side-effect counts are all directly observable from tracing the code.

## Failure Mode Being Tested

**SIDE_EFFECT_ORDER** (hidden_dependency) -- a per-item side effect is incorrectly batched, compounded by a legitimate batch-level distractor in the same file. Tests the model's ability to distinguish between two code paths with different effect granularity requirements.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot handle 3-file reasoning with distractor |
| 4o-mini | CSF | Likely confused by fast_process distractor |
| 5-mini | CSF | Distractor plus 3-file trace is near the boundary |

---

<a id="false-fix-deadlock"></a>

# Case: false_fix_deadlock

**Family:** concurrency
**Difficulty:** hard
**Bug Pattern:** circular lock wait (deadlock from opposite lock ordering)
**Causal Depth:** 2 deep
**Pearl Level:** L2
**Trap Type:** F6: removing locks or adding timeout are wrong fixes

---

## Task Prompt

> Fix the resource transfer system so that interleaved A-to-B and B-to-A transfers complete without deadlock, while preserving total balance.

## What the Code Does

`resources.py` implements a simulated resource transfer system with two resources ("A" and "B"), a simple lock mechanism (`_locks` dict), and deterministic step-based execution.

Transfer A-to-B locks A first, then B:

```python
def make_transfer_a_to_b_steps(amount):
    def step_lock_a():
        acquire("A")
        return "locked_A"

    def step_lock_b_and_transfer():
        acquire("B")
        _state["A"] -= amount
        _state["B"] += amount
        release("B")
        release("A")
        return "transferred_a_to_b"

    return step_lock_a, step_lock_b_and_transfer
```

Transfer B-to-A locks B first, then A (opposite order):

```python
def make_transfer_b_to_a_steps(amount):
    def step_lock_b():
        acquire("B")
        return "locked_B"

    def step_lock_a_and_transfer():
        acquire("A")  # DEADLOCK: A is held by the other transfer
        ...
```

- `sequential_transfers()`: A-to-B completes fully, then B-to-A. No deadlock.
- `interleaved_transfers()`: Step 1 locks A (for A-to-B), Step 2 locks B (for B-to-A), Step 3 A-to-B tries to lock B -- deadlock. A `RuntimeError` is raised by the `acquire` function.

## The Bug

The two transfer functions use opposite lock ordering: A-to-B acquires A then B, while B-to-A acquires B then A. Under interleaving, after step 1 (lock A) and step 2 (lock B), both resources are held by different transfers. Step 3 (A-to-B tries to lock B) fails because B is already held. This is the classic circular-wait deadlock pattern.

The violated invariant: transfers must complete without deadlock and the total balance (A + B) must remain 200.

## The Correct Fix

The reference fix (`reference_fixes/false_fix_deadlock.py`) applies two changes:

1. **Canonical lock ordering:** Both transfers acquire locks in the same order (A first, then B), regardless of transfer direction.
2. **Atomic steps:** Each transfer is a single atomic step (both locks + transfer + release), preventing interleaving between lock acquisition and transfer.

```python
def make_transfer_b_to_a_steps(amount):
    def step_atomic_transfer():
        acquire("A")  # canonical order: A first
        acquire("B")
        _state["B"] -= amount
        _state["A"] += amount
        release("B")
        release("A")
        return "transferred_b_to_a"

    def step_noop():
        return "noop"

    return step_atomic_transfer, step_noop
```

Both transfers use A-then-B ordering and are fully atomic. Under interleaving, the first atomic step completes its full lock-transfer-release cycle before the second runs, so no circular wait occurs.

## What the Test Checks

1. `sequential_transfers()` must not deadlock (no `"error"` key in result).
2. Sequential total `A + B` must equal 200.
3. `interleaved_transfers()` must not deadlock (no `"error"` key in result).
4. Interleaved total `A + B` must equal 200.

## Why This Is Difficult for LLMs

- **F6 trap: removing locks is a wrong fix.** A model might simply remove locking to avoid the deadlock, but this would violate data integrity in a real concurrent system. The test still checks balance conservation.
- **F6 trap: adding timeouts or try/except is a wrong fix.** Catching the `RuntimeError` and retrying or skipping does not fix the structural ordering problem.
- **Common wrong fix: only fixing one transfer.** A model might fix B-to-A's lock order but leave it as two steps, which still allows interleaving to cause the deadlock.
- **Two-part fix required:** Both canonical ordering AND atomicity are needed. Canonical ordering alone (without atomicity) still allows the interleaved schedule to hold one lock from each transfer simultaneously.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention (deep)

This is L2 "deep" because the model must identify two coordinated interventions: (1) canonical lock ordering to prevent circular wait, and (2) atomic step consolidation to prevent interleaving between lock acquisitions. Either intervention alone is insufficient under the given step schedule.

### Trap Type: F6: removing locks or adding timeout are wrong fixes

The F6 trap here is particularly strong because the code already demonstrates the deadlock with a clear error message. The temptation is to "handle" the error (catch it, retry, remove locks) rather than fix the structural cause. The correct fix requires understanding that lock ordering is the root cause and that atomicity is needed within the step-function framework.

### Why This Case Is L2 Deep, Not L1 or L3

- **Not L1:** L1 would be recognizing "opposite lock ordering causes deadlock." The model must design the specific fix (canonical ordering + atomicity).
- **Not standard L2:** It is "L2 deep" because the fix has two necessary components. Standard L2 cases have a single intervention point.
- **Not L3:** L3 requires counterfactual reasoning about structural vs. contingent causes. Here the cause is clear (opposite ordering + non-atomic steps), and the fix is deterministic. There is no ambiguity about which factor is structural vs. contingent.

## Failure Mode Being Tested

Circular lock wait (deadlock): two actors each hold a resource the other needs, caused by inconsistent lock acquisition ordering.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely removes locks, adds try/except, or applies a timeout. May not understand the step-function model well enough to make steps atomic. |
| 4o-mini | partial | May fix lock ordering but leave the two-step structure, which still deadlocks under the given interleaved schedule. Or may make steps atomic without fixing ordering. |
| 5-mini | pass/partial | Should recognize canonical lock ordering. Whether it also makes steps atomic depends on how well it understands the step-function framework. |

---

<a id="feature-flag-drift"></a>

# Case: feature_flag_drift

**Family:** Flag Drift
**Difficulty:** Hard (V1)
**Bug Pattern:** FLAG_DRIFT
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F3 Confounding + F6 Mechanism: pass use_new_pricing as a parameter but pricing.compute_price still reads is_enabled('new_pricing') from global flags -- the parameter is ignored unless compute_price is also changed

---

## Task Prompt

> The enable/disable pattern in checkout is ugly. Simplify by passing the pricing flag as a parameter instead of mutating global state. Return the updated code.

## What the Code Does

The system has four modules implementing feature-flagged pricing:

- **flags.py** manages global feature flags:
  ```python
  _flags = {"new_pricing": False, "v2_api": False, "audit_mode": True}
  def is_enabled(flag):   # Reads from _flags
  def enable(flag):        # Sets _flags[flag] = True
  def disable(flag):       # Sets _flags[flag] = False
  ```

- **pricing.py** computes prices based on the global flag:
  ```python
  def compute_price(base, qty):
      if is_enabled("new_pricing"):    # Reads GLOBAL flag
          return _v2_price(base, qty)  # 10% discount for qty >= 10
      return _v1_price(base, qty)      # base * qty, no discount
  ```

- **billing.py** creates invoices by calling `compute_price` for each item:
  ```python
  def create_invoice(customer, items):
      for item in items:
          price = compute_price(item["base"], item["qty"])  # Uses global flag
          ...
  ```

- **api.py** orchestrates checkout with temporary flag mutation:
  ```python
  def checkout(customer, items, use_new_pricing=False):
      if use_new_pricing:
          enable("new_pricing")       # Temporarily enable
      invoice = create_invoice(customer, items)
      if use_new_pricing:
          disable("new_pricing")      # Restore
      return invoice
  ```

## The Bug

The buggy version (`api_buggy.py`) removes the enable/disable calls and simply ignores the parameter:

```python
def checkout(customer, items, use_new_pricing=False):
    invoice = create_invoice(customer, items)   # use_new_pricing is ignored
    return invoice
```

The model's natural "fix" is to pass `use_new_pricing` as a parameter to `create_invoice` and then to `compute_price`. But `compute_price` reads `is_enabled("new_pricing")` from the global `_flags` dict -- it does NOT accept a pricing mode parameter. Unless the model ALSO modifies `compute_price` to accept and use a parameter (or the flag is set globally), the parameter is silently ignored and v1 pricing is always used.

The result: `checkout("cust1", [{"sku": "A", "base": 100, "qty": 10}], use_new_pricing=True)` returns total=1000 (v1 pricing) instead of total=900 (v2 pricing with 10% discount).

## The Correct Fix

The reference fix (`reference_fixes/feature_flag_drift.py`) preserves the enable/disable pattern:

```python
def checkout(customer, items, use_new_pricing=False):
    if use_new_pricing:
        enable("new_pricing")
    invoice = create_invoice(customer, items)
    if use_new_pricing:
        disable("new_pricing")
    return invoice
```

An alternative correct fix would thread the parameter through the entire call chain: `checkout` -> `create_invoice` -> `compute_price`, modifying each function to accept and use a `use_new_pricing` parameter. But the reference fix takes the simpler approach of keeping the global flag mutation, which is the existing working behavior.

## What the Test Checks

1. Resets `_flags["new_pricing"] = False`.
2. Calls `checkout("cust1", [{"sku": "A", "base": 100, "qty": 10}], use_new_pricing=True)`.
3. Checks `invoice["total"] == 900` (v2 pricing: `100 * 10 * 0.9 = 900`).
4. Checks that `_flags["new_pricing"]` is `False` after checkout (flag cleaned up).

If the flag never propagates to `compute_price`, v1 pricing is used: `100 * 10 = 1000`, and the test fails.

## Why This Is Difficult for LLMs

1. **The "clean" solution is a trap:** Passing a parameter instead of mutating global state is universally considered better practice. The model will eagerly adopt this approach. But adding a `use_new_pricing` parameter to `checkout` (or even to `create_invoice`) accomplishes nothing unless `compute_price` is also modified -- and `compute_price` is in a different file (`pricing.py`).

2. **The call chain is three hops deep:** `checkout` -> `create_invoice` -> `compute_price` -> `is_enabled("new_pricing")`. The model must trace all three hops to understand where the flag is actually consumed.

3. **The existing code looks ugly but works:** The enable/disable pattern in the original `api.py` is indeed ugly (global state mutation, not thread-safe). But it WORKS because `compute_price` reads from the global flags. The "improvement" of passing a parameter breaks the working behavior.

4. **Partial fix is the common failure:** The model adds `use_new_pricing` as a parameter to `checkout` but doesn't propagate it through `create_invoice` and `compute_price`. This compiles, runs without errors, but silently ignores the flag.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about the intervention of removing enable/disable and adding a parameter:

1. Trace the current working path: `checkout` enables flag -> `create_invoice` -> `compute_price` -> `is_enabled("new_pricing")` reads `True` -> v2 pricing used.
2. Trace the "simplified" path: `checkout` passes `use_new_pricing=True` as parameter -> `create_invoice(customer, items)` -> `compute_price(base, qty)` -> `is_enabled("new_pricing")` reads `False` (flag was never set) -> v1 pricing used.
3. Conclude: the parameter is not connected to the decision point in `compute_price`.

### Trap Type: F3 Confounding + F6 Mechanism

**F3 (Confounding):** The model confounds "passing a parameter" with "the parameter being used." It sees `use_new_pricing` being passed and assumes the downstream code will respect it. But there is no connection between the parameter and `compute_price`'s `is_enabled` call -- they are completely separate mechanisms.

**F6 (Mechanism):** The model must understand the mechanism by which pricing decisions are made: `compute_price` calls `is_enabled("new_pricing")` which reads from the global `_flags` dict. No parameter passing, no dependency injection -- just a global read. Unless this mechanism is changed, no amount of parameter threading affects the pricing decision.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug requires tracing through four files (`api.py` -> `billing.py` -> `pricing.py` -> `flags.py`) to understand where the pricing flag is consumed and why a parameter at the API level doesn't reach it.
- **Not L3 (counterfactual):** The reasoning is forward-traceable: "If I remove enable/disable and add a parameter, trace the execution to see if compute_price ever sees the flag." No counterfactual reasoning about alternative designs is needed.
- **L2 (deep intervention):** The model must simulate the code change (intervention) and trace the multi-step causal chain to discover that the parameter is disconnected from the decision point.

## Failure Mode Being Tested

FLAG_DRIFT -- The feature flag's effect drifts away from the API parameter because the flag consumption point (`compute_price` reading global state) is decoupled from the flag control point (`checkout` setting a parameter). The parameter and the flag are two separate channels that the "simplified" code fails to connect.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will remove enable/disable and add a parameter to checkout; cannot trace the 3-hop call chain to compute_price |
| 4o-mini | CSF | Likely passes parameter to create_invoice but not to compute_price; partial fix that silently fails |
| 5-mini | CSF | May trace deeper but the "pass parameter" instinct is strong; unlikely to modify compute_price in pricing.py |

---

<a id="hidden-dep-multihop"></a>

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

---

<a id="index-misalign-a"></a>

# Case: index_misalign_a

**Family:** index_misalign
**Difficulty:** A (Easy)
**Bug Pattern:** partial_state_update
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1: Selection (only some parallel structures updated)

---

## Task Prompt

> Refactor this report builder for clarity. Return the updated code.

## What the Code Does

A single-file report builder in `report.py` using parallel arrays:

```python
_labels = []
_values = []

def add_entry(label, value, position=None):
    if position is not None:
        _labels.insert(position, label)
        # BUG: values always appended instead of inserted at position
        _values.append(value)
    else:
        _labels.append(label)
        _values.append(value)
```

`get_entry(index)` returns `(_labels[index], _values[index])`. `get_all()` zips the two arrays together.

## The Bug

When `position` is specified, `_labels` is correctly inserted at the given index, but `_values` is always appended to the end. This causes the parallel arrays to become desynchronized: after an insert at position 0, the label is at index 0 but the corresponding value is at the last index.

For example, after `add_entry("a", 1)`, `add_entry("b", 2)`, `add_entry("c", 3, position=0)`:
- `_labels` = `["c", "a", "b"]` (c inserted at 0)
- `_values` = `[1, 2, 3]` (3 appended to end)
- `get_entry(0)` returns `("c", 1)` instead of `("c", 3)`

**Violated invariant:** Parallel arrays must stay aligned.

## The Correct Fix

Change `_values.append(value)` to `_values.insert(position, value)` on line 16 of `report.py`:

```python
_values.insert(position, value)  # FIX: insert at position instead of append
```

**Lines changed:** 1

## What the Test Checks

1. After adding "alpha"/10, "beta"/20, then "gamma"/30 at position 0:
   - `get_entry(0)` returns `("gamma", 30)`
2. `get_entry(1)` returns `("alpha", 10)` -- confirming full alignment

## Why This Is Difficult for LLMs

- **Refactor framing hides the bug:** The task says "refactor for clarity," not "fix a bug." A model focused on naming or structure may preserve the append.
- **append vs insert are both valid list operations:** The model must recognize that when `_labels` uses `insert`, `_values` must also use `insert` to maintain parallelism.
- **Bug only manifests with position argument:** When `position` is None (the else branch), both arrays use `append` and stay aligned. The bug is only visible when the optional `position` parameter is used.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible by reading the `add_entry` function: in the `if position is not None` branch, `_labels.insert(position, ...)` is paired with `_values.append(...)`. The asymmetry is directly observable without cross-function or cross-file reasoning.

### Trap Type: F1: Selection (only some parallel structures updated)

The `add_entry` function performs a selective update: it correctly uses `insert` for `_labels` but selects `append` for `_values`. Only one of the two parallel structures is updated consistently -- the other is treated differently, causing a selection-based misalignment.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-file or cross-function tracing is needed. Both arrays and the bug are in the same function.
- **Not L3:** No counterfactual or multi-step reasoning is required.

## Failure Mode Being Tested

**partial_state_update** -- Two parallel data structures that must stay synchronized are updated with different operations (insert vs append), causing them to silently drift apart.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May focus on cosmetic refactoring and preserve the append/insert asymmetry |
| 4o-mini | Heuristic | Likely to notice the asymmetry during refactoring |
| 5-mini | CSF | Should identify the insert/append mismatch through parallel structure analysis |

---

<a id="index-misalign-b"></a>

# Case: index_misalign_b

**Family:** index_misalign
**Difficulty:** B (Medium)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1: Selection (only some parallel structures updated)

---

## Task Prompt

> Report columns are misaligned after deletion. Fix. Return the updated code.

## What the Code Does

Two files implement a tabular report system:

**`data.py`** provides `make_row(*values)` which converts positional values to a list, and `validate_row(row, expected_cols)` for validation.

**`report.py`** contains a `Report` class:

```python
class Report:
    def __init__(self, headers):
        self.headers = list(headers)
        self.rows = []

    def delete_column(self, index):
        # BUG: removes header but does NOT remove from rows
        del self.headers[index]

    def render(self):
        result = []
        for row in self.rows:
            result.append(dict(zip(self.headers, row)))
        return result
```

`render()` uses `zip(self.headers, row)` to create dicts. If headers and rows have different column counts, the zip produces incorrect key-value pairings.

## The Bug

`delete_column(index)` removes the header at `index` but does not remove the corresponding element from each row. After deleting column 1 ("age") from a 3-column table:
- `self.headers` = `["name", "city"]` (2 elements)
- `self.rows[0]` = `["Alice", 30, "NYC"]` (still 3 elements)
- `render()` zips: `{"name": "Alice", "city": 30}` -- "city" maps to 30 (the age value), not "NYC"

**Violated invariant:** Parallel arrays must stay aligned.

## The Correct Fix

Add row-element deletion to `delete_column` in `report.py` (after line 24):

```python
def delete_column(self, index):
    del self.headers[index]
    # FIX: also remove from each row
    for row in self.rows:
        del row[index]
```

**Lines changed:** 1 (add the for-loop with del)

## What the Test Checks

1. Create a Report with headers ["name", "age", "city"] and two rows
2. Delete column 1 ("age")
3. `render()` first row has `"name"` = `"Alice"` (not shifted)
4. `render()` first row has `"city"` = `"NYC"` (not the age value 30)

## Why This Is Difficult for LLMs

- **Trap: render looks correct in isolation.** The `render()` method correctly uses `zip(self.headers, row)` -- it has no bug itself. The bug is in `delete_column` which leaves the data in an inconsistent state.
- **Cross-function reasoning required:** The model must understand that `delete_column`'s incomplete update will cause `render()` to produce wrong results. This requires tracing the data flow from mutation to consumption.
- **zip masks the error:** Python's `zip` silently truncates to the shorter iterable, so no IndexError is raised. The misalignment produces wrong data, not a crash.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens if I call delete_column(1) and then render()?" This requires:
1. Understanding that `delete_column` only modifies `headers`
2. Tracing the stale rows through `render()`
3. Recognizing that `zip` will pair misaligned elements

This is a cross-function intervention where the mutation in one method affects the output of another.

### Trap Type: F1: Selection (only some parallel structures updated)

`delete_column` selectively updates `self.headers` but not `self.rows`. The selection is incomplete: only one of the two parallel structures is modified, leaving the other stale and causing misalignment.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug requires reasoning across two methods (`delete_column` and `render`) and understanding how the incomplete update in one causes wrong output in the other.
- **Not L3:** No counterfactual chain across multiple files or multi-step temporal reasoning is needed. The intervention is a straightforward two-step trace: delete -> render.

## Failure Mode Being Tested

**partial_state_update** -- A mutation operation updates one parallel structure (headers) but not the other (rows), causing them to silently drift apart. The consumer (`render`) produces wrong results without raising an error.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not trace from delete_column to render to see the misalignment |
| 4o-mini | REI | May focus on render() (which looks correct) rather than delete_column |
| 5-mini | CSF | Should trace the data flow and identify the missing row update |

---

<a id="index-misalign-c"></a>

# Case: index_misalign_c

**Family:** index_misalign
**Difficulty:** C (Hard)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1: Selection (only some parallel structures updated)

---

## Task Prompt

> Report formatting breaks after inserting column. Fix. Return the updated code.

## What the Code Does

Three files implement a table report with formatting:

**`data.py`** provides `make_row(values, num_cols)` that pads/truncates a row to match column count, and `validate_table(headers, rows, widths)` that checks all three arrays have consistent lengths.

**`formatter.py`** provides `format_table(headers, rows, widths)` that uses `widths[i]` to pad each column with `ljust()`, and `recalculate_widths(headers, rows)` that computes optimal widths from actual data.

**`report.py`** contains a `Report` class with three parallel structures:

```python
class Report:
    def __init__(self, headers, default_width=10):
        self.headers = list(headers)
        self.rows = []
        self.column_widths = [default_width] * len(headers)

    def insert_column(self, position, header, default_value=""):
        self.headers.insert(position, header)
        for row in self.rows:
            row.insert(position, default_value)
        # BUG: column_widths not updated -- stays at old length
```

## The Bug

`insert_column()` correctly updates `self.headers` (insert at position) and `self.rows` (insert default_value at position in each row), but does NOT update `self.column_widths`. After inserting a column:
- `self.headers` has N+1 elements
- Each row has N+1 elements
- `self.column_widths` still has N elements

This causes `validate()` to fail (header/width count mismatch) and `render()` to crash with an IndexError when `format_table` tries to access `widths[N]`.

**Violated invariant:** Parallel arrays must stay aligned.

## The Correct Fix

Add `column_widths.insert()` to `insert_column` in `report.py` (line 30):

```python
self.column_widths.insert(position, len(header))  # FIX: also insert into column_widths
```

**Lines changed:** 1

## What the Test Checks

1. Create a Report with headers ["name", "score"] and two rows
2. Insert column at position 1 with header "grade" and default value "A"
3. `validate()` returns `(True, "ok")` -- all three structures are in sync
4. `render()` does not crash -- widths array matches header count

## Why This Is Difficult for LLMs

- **Trap: `recalculate_widths` exists but is not called.** The `formatter.py` module provides `recalculate_widths(headers, rows)` which could be used to fix the widths. A model might call this function instead of directly inserting into `column_widths`. While calling `recalculate_widths` could work, the minimal fix is a single insert.
- **Three parallel structures:** The model must track headers, rows, AND column_widths simultaneously. The first two are correctly updated, creating a false sense of completeness.
- **Cross-file error manifestation:** The bug is in `report.py`'s `insert_column`, but the crash happens in `formatter.py`'s `format_table` when it accesses `widths[i]` beyond the array length.
- **Two out of three is almost right:** Headers and rows are correctly updated. The model may check those two, see they match, and conclude the function is correct without checking the third structure.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through `insert_column` and its downstream effects:
1. Tracing `insert_column` to see that headers and rows are updated but widths are not -- deterministic state tracing
2. Tracing `render()` into `format_table()` in `formatter.py` to see that it requires `widths` to match `headers` -- mechanism verification
3. Understanding that `validate_table()` in `data.py` checks the header/width alignment -- forward path analysis
4. Recognizing that `recalculate_widths` exists as a potential fix mechanism but isn't called

This is multi-step causal propagation across three files tracking three parallel structures through deterministic code paths.

### Trap Type: F1: Selection (only some parallel structures updated)

`insert_column` selectively updates two of three parallel structures (headers and rows) but not the third (column_widths). The selection is 2/3 complete -- close enough to look correct on cursory inspection, but the missing third structure causes downstream failures.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug requires understanding three parallel structures across three files.
- **L2 (deep):** The model must trace the cascade: insert_column -> render -> format_table -> IndexError, tracking three parallel structures (headers, rows, widths) and verifying the mechanism at each step. It must also consider whether `recalculate_widths` or `validate_table` provide alternative fix paths. This is multi-step causal propagation crossing multiple module boundaries.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The array lengths, the insert operations, and the IndexError are all directly observable from tracing the actual execution forward.

## Failure Mode Being Tested

**partial_state_update** -- A mutation operation updates two of three parallel structures, leaving the third stale. The error manifests as a crash in a different module that consumes the inconsistent state.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot track three parallel structures across three files |
| 4o-mini | CSF | May notice headers/rows are updated and stop checking, missing column_widths |
| 5-mini | CSF | Best chance but may be distracted by recalculate_widths as an alternative fix |

---

<a id="invariant-partial-fail"></a>

# Case: invariant_partial_fail

**Family:** Invariant Violation
**Difficulty:** Hard (V1)
**Bug Pattern:** INVARIANT_VIOLATION
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1 Selection + F6 Mechanism: extract a clean debit+credit helper and move all logging to a wrapper, without adding rollback

---

## Task Prompt

> The execute_transfer function has too many logging calls mixed with business logic. Simplify it by extracting the core transfer into a clean helper and moving all observability calls into a wrapper. Return the updated code.

## What the Code Does

The system has four modules implementing a transfer service:

- **models.py** defines `Account(account_id, balance)`.

- **ledger.py** appends structured entries to `_entries` for audit trail: `record_debit`, `record_credit`, `record_transfer_attempt`.

- **audit.py** appends alerts to `_alerts`: `emit_transfer_event`, `emit_failure_alert`.

- **transfer_service.py** contains the core logic:

```python
def execute_transfer(sender, receiver, amount):
    validate_transfer(sender, amount)
    record_transfer_attempt(sender.account_id, receiver.account_id, amount)
    sender.balance -= amount              # DEBIT
    record_debit(sender.account_id, amount)
    if random.random() < 0.3:             # Simulated transient failure
        emit_failure_alert(...)
        raise RuntimeError("transient failure during credit")
    receiver.balance += amount            # CREDIT
    record_credit(receiver.account_id, amount)
    emit_transfer_event(...)
```

The critical issue: between `sender.balance -= amount` (line 19) and `receiver.balance += amount` (line 29), a transient failure can occur. When it does, the sender has been debited but the receiver has NOT been credited. Money vanishes.

## The Bug

The task asks to "extract the core transfer into a clean helper and move all observability calls into a wrapper." The trap is that the model will faithfully separate logging from business logic but fail to notice the partial-failure invariant violation that already exists in the code. The "clean" refactored version will preserve the bug: debit happens, then failure occurs, no rollback, money is lost.

The invariant violated: `sender.balance + receiver.balance` must be conserved at all times. After a failed transfer, the sender loses money that the receiver never receives.

## The Correct Fix

The reference fix (`reference_fixes/invariant_partial_fail.py`) wraps the failure-prone section in a try/except that restores the sender's balance:

```python
def execute_transfer(sender, receiver, amount):
    validate_transfer(sender, amount)
    record_transfer_attempt(sender.account_id, receiver.account_id, amount)
    sender.balance -= amount
    record_debit(sender.account_id, amount)
    try:
        if random.random() < 0.3:
            emit_failure_alert(...)
            raise RuntimeError("transient failure during credit")
        receiver.balance += amount
        record_credit(receiver.account_id, amount)
    except Exception:
        sender.balance += amount          # ROLLBACK
        raise
    emit_transfer_event(...)
```

The key change: `sender.balance += amount` in the except block restores the debited amount when the credit phase fails.

## What the Test Checks

1. Creates `sender = Account("s1", 100)` and `receiver = Account("r1", 0)`, recording `initial_total = 100`.
2. Patches `random.random` to return `0.0` (always triggers the failure path since `0.0 < 0.3`).
3. Calls `execute_transfer(sender, receiver, 50)` expecting a `RuntimeError`.
4. Asserts `sender.balance + receiver.balance == initial_total` (balance conservation).

If no rollback exists, sender.balance is 50 and receiver.balance is 0, total is 50 instead of 100.

## Why This Is Difficult for LLMs

1. **Selection bias (F1):** The task frames the problem as "too many logging calls mixed with business logic." The model selects for the refactoring goal (separate concerns) and ignores the latent atomicity bug. The bug is pre-existing, not introduced by the refactoring.

2. **Mechanism ignorance (F6):** The model must understand the mechanism of partial failure: that `sender.balance -= amount` is an immediate, irrevocable mutation, and that the `raise` on line 27 exits the function before `receiver.balance += amount` executes. Without understanding this mechanism, the model cannot see why rollback is needed.

3. **The task misdirects:** The prompt says "simplify" and "extract" -- both suggest the code is functionally correct and only needs structural improvement. The model has no reason to suspect a correctness bug exists.

4. **Logging vs correctness confusion:** The audit/ledger calls look like the "noise" the task wants removed. The model focuses on moving those calls and doesn't examine the interleaving of mutations and failure points.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about an intervention (refactoring the function) and its causal consequences:

1. Identify that `sender.balance -= amount` is a side effect that occurs before the potential failure point.
2. Trace forward: if `RuntimeError` is raised at line 27, execution jumps past `receiver.balance += amount`.
3. Conclude: the sender's balance is reduced but the receiver's is not -- money is destroyed.
4. Recognize that any refactored version must either make the debit-credit atomic or add compensating logic (rollback).

### Trap Type: F1 Selection + F6 Mechanism

**F1 (Selection):** The model selects the task's framing (refactor for clarity) and de-selects the latent bug (atomicity violation). The task never mentions a bug -- it says "simplify" -- so the model has no trigger to look for one.

**F6 (Mechanism):** Understanding why rollback is needed requires mechanistic reasoning about exception propagation, mutable state, and the non-atomic nature of sequential mutations. The model must understand that `balance -= amount` cannot be "un-done" by exception handling alone -- explicit compensation is required.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug spans the interaction between `sender.balance -= amount`, the random failure, and the missing `receiver.balance += amount`. It requires understanding control flow through exceptions across multiple mutations.
- **Not L3 (counterfactual):** The causal chain is forward-traceable: "debit happens, then exception, then no credit, therefore money lost." No counterfactual reasoning about alternative program structures is needed.
- **L2 (deep intervention):** The model must simulate what happens when the function is refactored (intervention) and trace the failure path to discover that the invariant violation persists (or is introduced by removing interleaved safety logic).

## Failure Mode Being Tested

INVARIANT_VIOLATION -- The financial conservation invariant (`sender.balance + receiver.balance == constant`) is violated when the debit succeeds but the credit fails, and no compensating rollback exists.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will extract helper and move logging without noticing the atomicity gap |
| 4o-mini | CSF | Likely produces a clean refactoring that preserves the existing bug; no trigger to add rollback |
| 5-mini | CSF | May recognize the failure path but unlikely to add rollback when the task says "simplify" not "fix" |

---

<a id="l3-state-pipeline"></a>

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

---

<a id="lazy-init-a"></a>

# Case: lazy_init_a

**Family:** lazy_init
**Difficulty:** A (Easy)
**Bug Pattern:** execution_model_mismatch
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F4 Direction: cause (import-time capture) appears to be effect (stale read)

---

## Task Prompt

> Refactor this settings module for clarity. Return the updated code.

## What the Code Does

A single-file service module with eagerly captured settings. A module-level `_settings` dict holds configuration. A second module-level variable `_default_host` captures `_settings["host"]` at import time. Functions allow configuring settings and reading the host, but `get_host()` reads from the eagerly captured variable rather than the live settings dict.

### Files

**service.py**
- `_settings = {"host": "localhost", "port": 8080, "debug": False}` -- module-level settings dict
- `_default_host = _settings["host"]` -- eagerly captured at import time (BUG)
- `get_host()` -- returns `_default_host` (the stale captured value)
- `get_settings()` -- returns a copy of `_settings` (works correctly)
- `reset_settings()` -- reassigns `_settings` to fresh defaults
- `configure(host=None, port=None, debug=None)` -- updates `_settings` fields in-place

## The Bug

Line 6: `_default_host = _settings["host"]` captures the string `"localhost"` at import time. Since strings are immutable in Python, `_default_host` is a copy of the value, not a reference to the dict entry. When `configure(host="prod.example.com")` updates `_settings["host"]`, `_default_host` still holds `"localhost"`. `get_host()` returns the stale value.

The invariant violated: `get_host()` must reflect changes made via `configure()`.

## The Correct Fix

Change `get_host()` to read from `_settings` lazily instead of returning the captured value:

```python
def get_host():
    """Return the current host setting."""
    return _settings["host"]  # was: return _default_host
```

And optionally remove the `_default_host` module-level variable. 2 lines changed.

## What the Test Checks

1. `configure(host="prod.example.com")` is called
2. `get_host()` must return `"prod.example.com"` (not stale `"localhost"`)

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" without mentioning any bug. An LLM may rename variables or add type hints without fixing the eager capture.
- `_default_host = _settings["host"]` looks like a reasonable optimization or alias. The fact that it captures a snapshot rather than a live reference is a subtle Python semantics issue.
- `get_settings()` works correctly (returns `dict(_settings)`), which may give the LLM the impression the module is sound.
- `reset_settings()` reassigns `_settings` to a new dict but doesn't update `_default_host`, compounding the staleness. But since the test only uses `configure()` (which mutates in-place), the `reset_settings` issue is secondary.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is associational: the model can observe that `_default_host` is assigned once at module level and `get_host()` returns it. The association between "import-time capture" and "stale value" is visible from reading the code.

### Trap Type: F4: Direction

The causal direction trap: the eager capture at import time is the CAUSE of the stale read, but it appears to be an EFFECT of wanting fast access. An LLM may interpret `_default_host` as an intentional optimization (caching the host for performance) rather than recognizing it as the source of the bug. The apparent causal direction (performance optimization -> captured value) is the reverse of the actual direction (captured value -> stale read).

### Why This Case Is L1, Not L2/L3

- L1 because the entire bug is visible in a single file. The eager capture, the configure function, and the stale read are all in `service.py`.
- Not L2 because no cross-function or cross-file tracing is needed.
- Not L3 because no temporal reasoning or counterfactual simulation is required.

## Failure Mode Being Tested

Execution model mismatch: the code assumes that `_default_host` will track changes to `_settings["host"]`, but Python's execution model means module-level assignments run once at import time. The developer's mental model (live reference) doesn't match Python's actual behavior (snapshot).

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to treat _default_host as intentional; cosmetic refactoring only |
| 4o-mini | Heuristic | May recognize the eager-capture pattern from training data |
| 5-mini | CSF | Should identify the mismatch between import-time capture and runtime configuration |

*These are hypotheses, not measurements.*

---

<a id="lazy-init-b"></a>

# Case: lazy_init_b

**Family:** lazy_init
**Difficulty:** B (Medium)
**Bug Pattern:** execution_model_mismatch
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F6 Mechanism: import-time capture mechanism silently breaks reset lifecycle

---

## Task Prompt

> After resetting config, client still uses old timeout. Fix. Return the updated code.

## What the Code Does

A two-file config-client system. The config module provides lazy-loaded configuration with reset and override capabilities. The client module imports and captures the config at import time, creating a stale reference that survives config resets.

### Files

**config.py**
- `_config = None` -- lazy-load sentinel
- `_load_config()` -- returns default config dict `{"db_url": "postgres://localhost/app", "timeout": 30}`
- `get_config()` -- lazy-loads config (creates on first call, caches thereafter)
- `reset_config()` -- sets `_config = None` (next `get_config()` will reload)
- `set_config(key, value)` -- overrides a config value in the current config dict

**client.py**
- `_client_config = get_config()` -- eagerly captures config dict at import time (BUG)
- `get_db_url()` -- returns `_client_config["db_url"]`
- `get_timeout()` -- returns `_client_config["timeout"]`
- `connect()` -- simulates a DB connection (distractor)

## The Bug

In `client.py`, line 6: `_client_config = get_config()` runs at import time. This captures a reference to the config dict object. When `reset_config()` sets `_config = None` in config.py and `set_config("timeout", 99)` creates a NEW dict, `_client_config` in client.py still points to the OLD dict object. `get_timeout()` returns the old timeout value (30), not the new one (99).

The key mechanism: `reset_config()` doesn't mutate the existing dict -- it replaces the module-level reference with `None`. When `set_config` later calls `get_config()`, a fresh dict is created. But `_client_config` was captured before the reset and still points to the original dict.

## The Correct Fix

Change `client.py` to read config lazily instead of capturing at import time:

```python
# Remove: _client_config = get_config()

def get_db_url():
    """Return the database URL the client is using."""
    return get_config()["db_url"]  # was: return _client_config["db_url"]

def get_timeout():
    """Return the timeout the client is using."""
    return get_config()["timeout"]  # was: return _client_config["timeout"]
```

4 lines changed (remove module-level capture, change 2 function bodies, optionally update connect()).

## What the Test Checks

1. `reset_config()` resets the config
2. `set_config("timeout", 99)` overrides the timeout
3. `get_timeout()` must return `99` (not stale `30`)

## Why This Is Difficult for LLMs

- The trap: the client correctly imports `get_config` from config.py. The import itself is fine -- the problem is the eager CALL at module level. An LLM may see the import and think the dependency is correctly established.
- `config.py` is well-designed with lazy loading and reset support. The bug is entirely in how `client.py` uses it. An LLM might focus on config.py looking for bugs there.
- The `connect()` function in client.py is a distractor that adds complexity without being related to the bug.
- An LLM might try to fix this by making `reset_config()` also update `client._client_config`, which would work but creates a tight coupling. The correct fix is to make the client read lazily.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about where to intervene in the causal chain: `import time -> get_config() called -> dict captured -> reset_config() creates new dict -> _client_config still points to old dict`. The correct intervention is to change the mechanism from eager capture to lazy access. The model must also reason about NOT intervening in config.py (which works correctly).

### Trap Type: F6: Mechanism

The mechanism trap: `get_config()` is designed for lazy loading (it creates the config only when called, returns cached version thereafter). But by calling it at module level in client.py, the lazy mechanism is bypassed and converted into eager capture. The mechanism looks correct in isolation (config.py's lazy loading works) but the way client.py invokes it subverts the intended lifecycle. `reset_config()` breaks the mechanism because it assumes all consumers will call `get_config()` again, but the client has already captured its own reference.

### Why This Case Is L2, Not L1/L3

- Not L1 because the bug requires cross-file reasoning: the root cause is in client.py's import-time call, but understanding WHY it's wrong requires understanding config.py's reset mechanism.
- L2 because the model must reason about which intervention (lazy access in client.py, not changes to config.py) will fix the stale reference problem.
- Not L3 because the causal chain involves only two files and a single reset-then-read sequence, not a multi-step temporal scenario.

## Failure Mode Being Tested

Execution model mismatch: the client assumes that capturing `get_config()` at import time provides a live reference to the config. But Python's module-level code runs once, and `reset_config()` creates a new dict object rather than mutating the existing one. The client's reference becomes stale after reset.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not understand the import-time capture vs. reset lifecycle interaction |
| 4o-mini | REI | May try to fix config.py rather than client.py, or add coupling between modules |
| 5-mini | CSF | Should recognize the eager capture pattern and convert to lazy access |

*These are hypotheses, not measurements.*

---

<a id="lazy-init-c"></a>

# Case: lazy_init_c

**Family:** lazy_init
**Difficulty:** C (Hard)
**Bug Pattern:** execution_model_mismatch
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F6 Mechanism: import-time capture mechanism breaks reset propagation through chain

---

## Task Prompt

> Config reset doesn't propagate through client to handler. Fix. Return the updated code.

## What the Code Does

A three-file config-client-handler chain. Configuration flows from `config.py` through `client.py` to `handler.py`. The config module supports lazy loading and reset. The client captures config at import time, creating a stale reference. The handler imports functions from the client, so it inherits the staleness.

### Files

**config.py**
- `_config = None` -- lazy-load sentinel
- `_load_config()` -- returns `{"api_key": "default-key", "base_url": "https://api.example.com"}`
- `get_config()` -- lazy-loads config; returns cached dict after first call
- `reset_config()` -- sets `_config = None` (triggers fresh load on next access)
- `set_config(key, value)` -- overrides a config value

**client.py**
- `_client_cfg = get_config()` -- eagerly captures config at import time (BUG)
- `get_api_key()` -- returns `_client_cfg["api_key"]`
- `get_base_url()` -- returns `_client_cfg["base_url"]`
- `build_headers()` -- builds auth headers (distractor)

**handler.py**
- `make_request(endpoint)` -- builds request dict using `get_api_key()` and `get_base_url()` from client
- `health_check()` -- health endpoint (distractor)
- `format_endpoint(base, path)` -- URL formatter (distractor)

## The Bug

In `client.py`, line 8: `_client_cfg = get_config()` captures the config dict at import time. After `reset_config()` + `set_config(...)`, a NEW config dict is created in `config.py`, but `_client_cfg` still points to the OLD dict. When `handler.py` calls `get_api_key()` or `get_base_url()`, they read from the stale `_client_cfg`.

The causal chain: `config.py` (reset creates new dict) -> `client.py` (still holds old dict) -> `handler.py` (reads stale values from client). The staleness propagates through the entire chain because the client's eager capture acts as a broken link.

## The Correct Fix

Change `client.py` to read config lazily:

```python
# Remove: _client_cfg = get_config()

def get_api_key():
    """Return the API key the client uses."""
    return get_config()["api_key"]  # was: return _client_cfg["api_key"]

def get_base_url():
    """Return the base URL the client uses."""
    return get_config()["base_url"]  # was: return _client_cfg["base_url"]
```

4 lines changed (remove module-level capture, change 2 function bodies).

## What the Test Checks

1. `reset_config()` resets configuration
2. `set_config("api_key", "new-secret-key")` overrides the API key
3. `set_config("base_url", "https://new-api.example.com")` overrides the base URL
4. `make_request("users")` builds a request dict
5. `result["api_key"]` must be `"new-secret-key"` (not stale `"default-key"`)
6. `result["url"]` must contain `"new-api.example.com"` (not stale `"api.example.com"`)

## Why This Is Difficult for LLMs

- Three files with the bug in the middle layer (client.py). The symptom is in handler.py, the root cause mechanism is in client.py, and the correct behavior is defined by config.py.
- The trap: `client.refresh()` is mentioned in the case metadata as existing "but handler doesn't call it." However, in the actual code, no refresh function exists. The trap is that an LLM might try to add a refresh mechanism rather than fixing the fundamental eager capture.
- `handler.py` is completely correct -- it delegates to client functions as intended. An LLM that focuses on handler.py will find nothing to fix there.
- `config.py` is also correct -- its lazy loading and reset work properly. The bug is entirely in how client.py consumes the config API.
- The `build_headers()`, `health_check()`, and `format_endpoint()` functions are all distractors that add cognitive load.
- An LLM might try to propagate reset through the chain (resetting client, then handler), but the correct fix is to eliminate the eager capture entirely.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

This requires multi-step causal propagation across a three-component chain and a temporal sequence (reset -> set_config -> make_request). The model must perform deterministic state tracing across modules: trace `reset_config()` setting `_config = None`, then `set_config()` creating a new dict, then follow the call chain from `make_request()` -> `get_api_key()` -> `_client_cfg["api_key"]` and verify the mechanism -- `_client_cfg` was captured at import time and still points to the old dict. This is forward path analysis through three files to identify where the stale reference was created.

### Trap Type: F6: Mechanism

The mechanism trap is multi-layered:
1. `config.py`'s lazy loading mechanism works correctly in isolation
2. `client.py`'s import-time call to `get_config()` subverts the lazy mechanism by converting it to eager capture
3. `handler.py`'s delegation to client functions is correct but inherits the broken mechanism
4. The intended reset mechanism (`reset_config()` -> next `get_config()` reloads) is correct but client.py never calls `get_config()` again after import

The mechanism chain appears correct at each link but is broken at the import-time capture boundary.

### Why This Case Is L2 (deep), Not L1 or L3

- Not L1 because no single file reveals the bug. Each file looks correct in isolation.
- L2 (deep) because the model must perform multi-step causal propagation across a three-file chain: trace the temporal sequence (reset -> set_config -> make_request) and verify the mechanism at each boundary. The eager capture in the middle of the chain breaks propagation to the end -- this is deterministic state tracing across modules, requiring mechanism verification at the import-time boundary.
- Not L3 because all steps are deterministic -- the model follows code paths, not alternative worlds. The import-time capture, the reset creating a new dict, and the stale reference are all observable facts that can be traced forward through the code.

## Failure Mode Being Tested

Execution model mismatch in a multi-layer dependency chain. The eager capture at import time breaks the config lifecycle (lazy load -> use -> reset -> reload) by creating a stale snapshot that cannot be invalidated through the intended reset mechanism. The three-file chain means the staleness is invisible to both the config module (which works correctly) and the handler module (which delegates correctly).

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Very unlikely to trace the three-file dependency chain |
| 4o-mini | CSF | May identify the eager capture but struggle with whether to fix client.py or handler.py |
| 5-mini | CSF | Best chance but must correctly identify client.py as the single point of failure |

*These are hypotheses, not measurements.*

---

<a id="lost-update"></a>

# Case: lost_update

**Family:** concurrency
**Difficulty:** medium
**Bug Pattern:** read-modify-write race condition
**Causal Depth:** 2
**Pearl Level:** L2
**Trap Type:** F3: race as hidden shared state

---

## Task Prompt

> Fix the counter so that both sequential and interleaved double-increments produce a final value of 2.

## What the Code Does

`counter.py` implements a global counter (`_value`) with non-atomic read-modify-write increments, simulated deterministically via step functions.

`make_increment_steps()` splits an increment into two closures that share a `captured` dict:

```python
def step_read():
    captured["current"] = get()
    return ("read", captured["current"])

def step_write():
    _set(captured["current"] + 1)
    return ("write", captured["current"] + 1)
```

Two scenario functions execute two increments:
- `sequential_double_increment()`: runs read_a, write_a, read_b, write_b -- produces 2 (correct).
- `interleaved_double_increment()`: runs read_a, read_b, write_a, write_b -- both read 0, both write 1 (bug).

## The Bug

In `interleaved_double_increment()`, the step ordering is `[read_a, read_b, write_a, write_b]`. Both `step_read` closures execute before either `step_write`, so both capture `current = 0`. Both writes then set `_value = 0 + 1 = 1`. The second increment is silently lost.

The violated invariant: two increments must always produce `value = 2`, regardless of interleaving.

## The Correct Fix

The reference fix (`reference_fixes/lost_update.py`) makes each increment atomic by combining read and write into a single step:

```python
def make_increment_steps():
    def step_atomic_increment():
        current = get()
        _set(current + 1)
        return ("atomic_increment", current + 1)

    def step_noop():
        return ("noop",)

    return step_atomic_increment, step_noop
```

The function still returns two values to preserve the call-site interface, but the second step is a no-op. Under interleaving, the first atomic step reads 0 and writes 1, then the second atomic step reads 1 and writes 2.

## What the Test Checks

1. `sequential_double_increment()` must return 2.
2. `interleaved_double_increment()` must return 2.

Both assertions use strict equality (`!= 2`).

## Why This Is Difficult for LLMs

- **The interleaving is deterministic, not random.** There are no threads or locks. The bug is purely in the step ordering passed to `run_steps`. Models that associate concurrency bugs only with threading will miss this.
- **Common wrong fix: adding a lock.** There is no threading infrastructure. Adding `threading.Lock` does nothing because all steps run on one thread.
- **Common wrong fix: changing the step order.** Reordering the steps in `interleaved_double_increment` changes the test scenario rather than fixing the code.
- **The fix requires understanding closure capture.** The `captured` dict is shared state between `step_read` and `step_write`. The model must recognize that separating read and write into distinct schedulable units is the root cause.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention

The model must reason: "If I intervene by making read+write atomic (a single step), then even under the interleaved schedule, the second increment will see the result of the first." This is a counterfactual intervention on the code structure, not just observation (L1) of what happens.

### Trap Type: F3: race as hidden shared state

The hidden shared state is the global `_value` module variable. Each increment's `step_read` captures a snapshot into its own `captured` dict, but both snapshots reference the same global. The race is that two reads of the same global happen before either write, creating stale-read semantics. The "hidden" aspect is that `_value` is not passed as a parameter -- it is accessed through `get()` and `_set()`, obscuring the shared-state dependency.

### Why This Case Is L2, Not L1 or L3

- **Not L1:** L1 (association) would be recognizing "interleaved operations can cause bugs." That is insufficient here -- the model must identify which specific intervention (atomic step) prevents the lost update.
- **Not L3:** L3 (counterfactual) requires reasoning about structural vs. contingent causes or multiple independently necessary conditions. Here there is a single clear intervention point: make the increment atomic. No structural/contingent distinction or multi-factor but-for reasoning is needed.

## Failure Mode Being Tested

Read-modify-write race condition: two operations read the same pre-state, compute independently, and the second write overwrites the first's result.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely adds threading locks or reorders steps rather than merging read+write into one atomic step. |
| 4o-mini | partial | May recognize the stale-read problem but struggle with the step-function abstraction. Could try to add state checks rather than merging steps. |
| 5-mini | pass | Should identify the non-atomic read-write split and merge them, though may produce a slightly different structure than the reference fix. |

---

<a id="missing-branch-a"></a>

# Case: missing_branch_a

**Family:** missing_branch
**Difficulty:** A (Easy)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1: Selection (unrepresented subgroup in conditional)

---

## Task Prompt

> Refactor this access control for clarity. Return the updated code.

## What the Code Does

A single-file permission system maps roles to permission sets via a `ROLE_PERMISSIONS` dictionary in `permissions.py`:

```python
ROLE_PERMISSIONS = {
    "admin": {"read", "write", "delete", "manage_users"},
    "user": {"read", "write"},
    # BUG: "moderator" role is missing -- falls through to empty set
}
```

`get_permissions(role)` looks up the role with `.get(role, set())`, and `has_permission(role, action)` checks membership in the returned set.

## The Bug

The `ROLE_PERMISSIONS` dictionary handles `"admin"` and `"user"` but omits `"moderator"`. When a moderator is looked up, `.get()` silently returns the default `set()`, giving them zero permissions. There is no error, no exception -- the moderator simply gets an empty permission set.

**Violated invariant:** All valid roles must receive correct permissions.

## The Correct Fix

Add the `"moderator"` entry to `ROLE_PERMISSIONS` (line 6 in `permissions.py`):

```python
"moderator": {"read", "write", "delete"},  # FIX: added moderator role
```

**Lines changed:** 2 (one new dict entry + trailing structure)

## What the Test Checks

1. `get_permissions("moderator")` returns a non-empty set
2. The returned set includes `"read"`
3. The returned set includes `"delete"`

## Why This Is Difficult for LLMs

- **Refactor framing hides the bug:** The task says "refactor for clarity," not "fix a bug." A model focused on cosmetic improvements may restructure the code without adding the missing role.
- **Silent failure:** No error or exception occurs -- `.get()` with a default quietly produces an empty set, so a model that only traces execution for crashes will miss this.
- **Plausible completeness:** With two roles already present, the dictionary looks structurally complete. The model must recognize that the domain requires a third role that is not present.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is directly observable by inspecting the dictionary keys against the set of valid roles. No intervention or counterfactual reasoning is needed -- a simple pattern-matching observation ("moderator is a valid role but is not in the dict") suffices to identify the problem.

### Trap Type: F1: Selection (unrepresented subgroup in conditional)

The `ROLE_PERMISSIONS` dictionary is a selection mechanism: it selects which roles receive permissions. The "moderator" subgroup is unrepresented in this selection, creating a selection bias where only admin and user roles receive correct treatment. The bug is a classic case of an incomplete enumeration in a conditional/dispatch structure.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No intervention simulation is needed. The fix does not require tracing through cross-function calls or reasoning about what would change if a function were modified.
- **Not L3:** No multi-step counterfactual chain is involved. The bug and fix are co-located in a single dictionary in a single file.

## Failure Mode Being Tested

**edge_case_omission** -- A valid input category is silently dropped by an incomplete conditional/dispatch structure. This connects to the broader taxonomy of silent-failure bugs where code appears correct on casual inspection but fails for unrepresented subgroups.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May attempt surface-level refactoring without identifying the missing role |
| 4o-mini | Heuristic | Likely recognizes the pattern of incomplete dict but may not add the right permissions |
| 5-mini | CSF | Should identify the missing moderator entry through direct dictionary inspection |

---

<a id="missing-branch-b"></a>

# Case: missing_branch_b

**Family:** missing_branch
**Difficulty:** B (Medium)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1: Selection (unrepresented subgroup in conditional)

---

## Task Prompt

> Guest users get no access. Fix the role dispatch. Return the updated code.

## What the Code Does

Two files collaborate to provide role-based access control:

**`roles.py`** defines access-level functions for each role, including `guest_access()` which returns `{"read": True, "write": False, "delete": False}`.

**`auth.py`** has a dispatch table mapping role strings to handler functions:

```python
_ROLE_DISPATCH = {
    "admin": admin_access,
    "user": user_access,
    "moderator": moderator_access,
    # BUG: "guest" missing -- falls through to _default_access (no access)
}
```

`get_access(role)` uses `.get(role, _default_access)` to dispatch. When `"guest"` is looked up, it silently falls to `_default_access()` which returns all-False (no access), even though `guest_access()` is imported and available.

## The Bug

The `_ROLE_DISPATCH` dictionary in `auth.py` includes admin, user, and moderator but omits `"guest"`. The `guest_access` function is imported at line 3 but never wired into the dispatch table. When `get_access("guest")` is called, it falls through to `_default_access()`, giving guests zero access instead of read-only access.

**Violated invariant:** All valid roles must receive correct permissions.

## The Correct Fix

Add `"guest"` to `_ROLE_DISPATCH` in `auth.py` (line 11):

```python
"guest": guest_access,  # FIX: added guest to dispatch table
```

**Lines changed:** 2 (one new dict entry)

## What the Test Checks

1. `get_access("guest")` returns a dict with `read` = True
2. `get_access("guest")` returns a dict with `write` = False
3. `get_access("guest")` returns a dict with `delete` = False

## Why This Is Difficult for LLMs

- **Distractor: `validate_role` exists but doesn't fix dispatch.** The `roles.py` file defines the `guest_access` function correctly. A model might look at roles.py, see it is correct, and conclude no fix is needed.
- **Cross-file reasoning required:** The bug is in `auth.py`'s dispatch table, not in the role definition. The model must trace the call from `get_access` -> `.get()` -> `_default_access` to understand why guest gets no access.
- **Import already present:** `guest_access` is already imported in `auth.py` line 3, making the fix a single-line addition to the dispatch dict. But the model must recognize the gap between "imported" and "wired up."

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens if I call `get_access('guest')`?" This requires tracing through the dispatch table lookup in `auth.py`, recognizing the fallthrough to `_default_access`, and understanding that the fix must be applied to the dispatch dict -- not to the role definitions in `roles.py`.

### Trap Type: F1: Selection (unrepresented subgroup in conditional)

The `_ROLE_DISPATCH` dictionary selects which roles get proper access handlers. The "guest" subgroup is unrepresented despite having a correctly-defined handler function (`guest_access`) that is already imported. The selection mechanism silently excludes a valid input.

### Why This Case Is L2, Not L1/L3

- **Not L1:** Simple association (inspecting one file) is insufficient. The model must cross from `auth.py` to `roles.py` to understand that `guest_access` exists and is correct, and that the dispatch table is the problem.
- **Not L3:** No multi-step temporal chain or counterfactual reasoning across multiple execution paths is required. The intervention is a single cross-function trace: call -> dispatch -> fallback.

## Failure Mode Being Tested

**edge_case_omission** -- A valid role is silently dropped by an incomplete dispatch table, despite the handler function being correctly implemented and imported. The gap between "defined" and "connected" is the core failure surface.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Likely to miss the cross-file dispatch gap or try to fix roles.py instead |
| 4o-mini | REI | May focus on roles.py (which is correct) rather than the dispatch table in auth.py |
| 5-mini | CSF | Should trace the dispatch mechanism and identify the missing entry |

---

<a id="missing-branch-c"></a>

# Case: missing_branch_c

**Family:** missing_branch
**Difficulty:** C (Hard)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1: Selection (unrepresented subgroup in conditional)

---

## Task Prompt

> Service accounts denied despite middleware allowing. Fix. Return the updated code.

## What the Code Does

Three files form a layered access-control pipeline:

**`roles.py`** defines `ROLE_TYPES = {"admin", "user", "moderator", "service_account", "guest"}` and provides `get_role_level()` and `is_valid_role()`. The `service_account` role has privilege level 80.

**`middleware.py`** validates requests and attaches role context. `authenticate()` correctly recognizes `service_account` as an elevated role:

```python
if role in ("admin", "service_account", "moderator"):
    return {"role": role, "allowed": True, "elevated": True}
```

**`auth.py`** contains `authorize(request)` which calls `middleware.authenticate()` then dispatches on the role:

```python
if role == "admin": ...
elif role == "moderator": ...
elif role == "user": ...
elif role == "guest": ...
else:
    # Unknown role -- no access
    return {"can_read": False, "can_write": False, "can_admin": False}
```

The `service_account` role passes middleware authentication (allowed=True, elevated=True) but falls into the `else` branch in `authorize()`, getting zero permissions.

## The Bug

`auth.py::authorize()` handles admin, moderator, user, and guest but has no branch for `service_account`. The middleware correctly allows service accounts through (setting `allowed=True`), but the authorization handler treats them as unknown, returning all-False permissions.

**Violated invariant:** All valid roles must receive correct permissions.

## The Correct Fix

Add a `service_account` branch in `auth.py::authorize()` (between the admin and moderator checks):

```python
elif role == "service_account":  # FIX: added service_account branch
    return {"can_read": True, "can_write": True, "can_admin": False}
```

**Lines changed:** 2

## What the Test Checks

1. `authorize({"role": "service_account"})` returns `can_read` = True
2. `authorize({"role": "service_account"})` returns `can_write` = True
3. `authorize({"role": "service_account"})` returns `can_admin` = False

## Why This Is Difficult for LLMs

- **Trap: Fix middleware only.** A model might see that middleware handles service_account and conclude the fix should be there. But middleware is already correct -- the bug is in auth.py's handler.
- **Three-file reasoning:** The model must trace service_account through roles.py (valid role) -> middleware.py (allowed=True) -> auth.py (falls to else). This is a multi-hop cross-boundary chain.
- **Middleware masks the bug:** Because middleware returns `allowed=True` for service_account, the denial happens silently in a later stage. The model must not stop at the middleware success.
- **Permission assignment ambiguity:** The model must decide what permissions service_account should have. The role level (80, between admin=100 and moderator=60) and the pattern of other roles suggest read+write but not admin.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through the entire request pipeline: trace `service_account` from `roles.py` (valid role, level 80) through `middleware.py` (allowed=True, elevated=True) into `auth.py`'s `authorize()` function, where it falls into the `else` branch and receives all-False permissions. This is deterministic state tracing across modules -- multi-step causal propagation following the request through three layers to identify the missing branch. The model verifies the mechanism at each layer to understand that middleware's decision is necessary but not sufficient.

### Trap Type: F1: Selection (unrepresented subgroup in conditional)

The `authorize()` function's if/elif chain is a selection mechanism over roles. `service_account` is a valid, recognized role (present in ROLE_TYPES, handled by middleware) but is unrepresented in the authorization handler's selection logic. The selection gap spans a cross-boundary pipeline.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug is not visible from any single file. roles.py is correct, middleware.py is correct -- only auth.py is wrong, but understanding why requires the full pipeline context.
- **L2 (deep):** The model must trace the request through three files (roles -> middleware -> auth), verify the mechanism at each layer, and identify the missing branch in the `authorize()` if/elif chain. This is multi-step causal propagation across module boundaries with mechanism verification at each hop.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The role validation, middleware decision, and if/elif dispatch are all directly observable from tracing the actual execution path forward.

## Failure Mode Being Tested

**edge_case_omission** -- A valid input category passes early validation stages but is silently dropped at a later stage due to an incomplete conditional. The multi-layer pipeline makes the omission harder to detect because each layer independently appears correct.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the 3-file pipeline; likely to attempt fixes in the wrong file |
| 4o-mini | CSF | May identify the pipeline but fix middleware instead of auth.py, or assign wrong permissions |
| 5-mini | CSF | Best chance of tracing the full pipeline, but permission assignment is ambiguous |

---

<a id="mutable-default-a"></a>

# Case: mutable_default_a

**Family:** mutable_default
**Difficulty:** A (Easy)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F3 Confounding: default arg is hidden shared state

---

## Task Prompt

> Refactor this queue module for clarity. Return the updated code.

## What the Code Does

A single-file task queue module. Tasks are created as dicts with `name` and `priority` fields. The `enqueue` function adds a task to a queue and returns it. The `process` function processes all tasks in a queue.

### Files

**queue.py**
- `enqueue(task, queue=[])` -- adds task to queue and returns queue; default arg is a mutable list (BUG)
- `make_task(name, priority=1)` -- creates a task dict `{"name": name, "priority": priority}`
- `process(queue)` -- processes all tasks, returns list of result strings

## The Bug

Line 4: `def enqueue(task, queue=[])` uses a mutable default argument. In Python, default arguments are evaluated once at function definition time. The same list object is reused across all calls that don't provide an explicit `queue` argument. Tasks accumulate: the first call adds one task, the second call adds another task to the SAME list, resulting in a queue with two tasks when only one was intended.

The invariant violated: each call with a single task (no explicit queue) must return a list containing only that task.

## The Correct Fix

```python
def enqueue(task, queue=None):
    """Add a task to the queue and return the queue."""
    if queue is None:
        queue = []
    queue.append(task)
    return queue
```

2 lines changed (change default from `[]` to `None`, add `if queue is None: queue = []`).

## What the Test Checks

1. `make_task("alpha")` creates task 1
2. `make_task("beta")` creates task 2
3. `enqueue(t1)` returns queue 1
4. `enqueue(t2)` returns queue 2
5. `len(q2)` must be `1` (not `2` -- beta only, not alpha+beta)
6. `q2[0]["name"]` must be `"beta"`

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" without mentioning any bug. An LLM focused on cosmetic changes will leave the mutable default intact.
- `def f(items=[])` is one of the most well-known Python gotchas. However, it is precisely because it is "well-known" that an LLM might either (a) fix it automatically from pattern matching, or (b) assume the developer intended the accumulation behavior.
- The function works perfectly on the first call. The bug only manifests on the second and subsequent calls with no explicit queue argument.
- `process(queue)` works correctly, so the module appears functional if tested with only one enqueue call.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is associational: the model can observe `queue=[]` in the function signature and associate this with Python's mutable default argument behavior. The bug is recognizable from the syntax alone, without needing to trace execution across functions.

### Trap Type: F3: Confounding

The mutable default list `[]` is the hidden common cause (confounder). Each call to `enqueue` that relies on the default appears to create an independent queue, but all such calls secretly share the same list object. The confounding structure: the shared default list causally affects both call 1's return value and call 2's return value. Call 1 appears to be independent of call 2, but they are confounded by the shared mutable state.

### Why This Case Is L1, Not L2/L3

- L1 because the bug is identifiable from a single line (`queue=[]`) using basic Python knowledge. No cross-function reasoning is required.
- Not L2 because no intervention analysis or cross-file tracing is needed.
- Not L3 because no temporal reasoning or counterfactual simulation is required -- the pattern `def f(x=[])` is a known antipattern.

## Failure Mode Being Tested

Retry/state accumulation via mutable default argument. The default arg creates hidden persistent state that leaks between what should be independent function calls. This is the classic Python mutable default argument pitfall.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May not recognize the mutable default pattern; cosmetic refactoring only |
| 4o-mini | Heuristic | Likely recognizes def f(x=[]) as a known Python antipattern from training data |
| 5-mini | CSF | Should immediately identify and fix the mutable default argument |

*These are hypotheses, not measurements.*

---

<a id="mutable-default-b"></a>

# Case: mutable_default_b

**Family:** mutable_default
**Difficulty:** B (Medium)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L1-L2 boundary
**Pearl Level:** L1-L2 Boundary (deterministic state tracing of known antipattern)
**Trap Type:** F3 Confounding: default arg is hidden shared state

---

## Task Prompt

> Workers skip valid tasks on second batch. Fix. Return the updated code.

## What the Code Does

A two-file task processing system. The queue module handles task creation and enqueueing (correctly, with `None` default). The worker module processes batches with deduplication, but the dedup `seen` set uses a mutable default argument that persists across calls.

### Files

**queue.py**
- `create_task(name, priority=1)` -- creates a task dict with `status: "pending"`
- `enqueue(task, queue=None)` -- correctly uses `None` default + creates list inside function
- `dequeue(queue)` -- removes and returns first task

**worker.py**
- `process_batch(tasks, seen=set())` -- processes tasks, skipping those whose name is in `seen`; BUG: default `set()` persists across calls
- `summarize(results)` -- formats result count (distractor)

## The Bug

In `worker.py`, line 6: `def process_batch(tasks, seen=set())` uses a mutable default argument. The `seen` set persists across calls. On the first call, task names are added to `seen`. On the second call, any task with a name that appeared in the first batch is skipped as a "duplicate" even though it is a legitimate task in a new, independent batch.

Example: batch 1 has `["task_x", "task_y"]`. Batch 2 has `["task_x", "task_z"]`. After processing batch 1, `seen = {"task_x", "task_y"}`. When batch 2 is processed, `task_x` is in `seen` and gets skipped, even though it is a valid task in a new batch.

The invariant violated: each call to `process_batch` with a fresh batch must process ALL tasks in that batch.

## The Correct Fix

```python
def process_batch(tasks, seen=None):
    """Process a batch of tasks, skipping already-seen ones."""
    if seen is None:
        seen = set()
    results = []
    for task in tasks:
        ...
```

2 lines changed (change default from `set()` to `None`, add `if seen is None: seen = set()`).

## What the Test Checks

1. `batch1 = [{"name": "task_x"}, {"name": "task_y"}]` -- first batch
2. `batch2 = [{"name": "task_x"}, {"name": "task_z"}]` -- second batch (task_x repeated intentionally)
3. `process_batch(batch1)` processes both tasks
4. `process_batch(batch2)` must process BOTH tasks (including task_x)
5. `r2` must have names `["task_x", "task_z"]` (not just `["task_z"]`)
6. `len(r2)` must be `2`

## Why This Is Difficult for LLMs

- The trap: the `seen` set looks like an intentional deduplication optimization. An LLM might believe the persistence across calls is desired behavior (dedup across batches). The task prompt ("workers skip valid tasks") hints otherwise, but the code structure suggests dedup is a feature.
- The bug is in `worker.py` but `queue.py` is also present. The queue module correctly uses `None` default, which might make the LLM think the codebase already handles mutable defaults correctly.
- `set()` as a mutable default is less commonly discussed than `[]`. An LLM might not recognize `set()` as having the same pitfall as `[]`.
- An LLM might try to fix the `seen` set by clearing it at the end of the function, but this would break intentional intra-batch dedup. The correct fix is the `None` default pattern.

## Causal Reasoning Required (L1-L2 Boundary)

### Pearl Level: L1-L2 Boundary (Deterministic State Tracing)

This case sits at the L1-L2 boundary. The mutable default `set()` antipattern is the same class of bug as Level A's `queue=[]` — a well-known Python gotcha. The model must trace that `seen=set()` persists across calls, causing inter-batch state leaking. This is **deterministic state tracing**: follow the object identity of the default argument across two calls to the same function.

The difficulty increase from Level A is in **locating** the bug across two files (queue.py correctly uses `None`, worker.py doesn't) and **distinguishing** intentional intra-batch dedup from accidental inter-batch leaking. But the underlying reasoning is the same as Level A: recognize the mutable default, apply the `None` default pattern.

### Trap Type: F3: Confounding

The mutable default `set()` is the hidden confounder. Batch 1 and batch 2 appear to be processed independently (separate `process_batch` calls), but they share state through the `seen` set. The confounding is more subtle than in Level A because the `seen` set's purpose (deduplication) makes the sharing look intentional. The confounder masquerades as a feature.

### Why This Case Is L1-L2 Boundary, Not L1 or Full L2

- Not pure L1 because the bug requires cross-file awareness (queue.py correctly uses `None` default, but worker.py doesn't) and understanding the semantic difference between intra-batch dedup (correct) and inter-batch state leaking (bug).
- Not full L2 (Intervention) because no causal graph reasoning is required. The model traces a deterministic behavior of Python's default argument evaluation — the same pattern as Level A, just harder to find across two files.
- Not L3 because the chain is two calls to the same function, not a multi-module state evolution.

## Failure Mode Being Tested

Retry/state accumulation via mutable default argument, but disguised as a deduplication feature. The `seen` set serves a legitimate purpose within a single call but its persistence across calls is a bug. This tests whether the model can distinguish between intended state retention and accidental state leaking.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not recognize set() as a mutable default issue |
| 4o-mini | REI | May think the seen set persistence is intentional dedup behavior |
| 5-mini | CSF | Should recognize the mutable default pattern and apply the None default fix |

*These are hypotheses, not measurements.*

---

<a id="mutable-default-c"></a>

# Case: mutable_default_c

**Family:** mutable_default
**Difficulty:** C (Hard)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L2
**Pearl Level:** L2 Intervention (multi-hop state propagation tracing through decorator closure)
**Trap Type:** F3 Confounding: default arg is hidden shared state

---

## Task Prompt

> Scheduler history is shared across jobs. Fix. Return the updated code.

## What the Code Does

A three-file task scheduling system with a decorator that tracks call history. The queue module handles task creation. The worker module processes tasks. The scheduler module defines a `with_history` decorator that records call history for decorated functions, but uses a shared module-level list as the default history, causing all decorated functions to share the same history.

### Files

**queue.py**
- `create_task(name, priority=1)` -- creates a task dict
- `enqueue_all(tasks, queue=None)` -- enqueues multiple tasks (correctly uses `None` default)
- `drain(queue)` -- removes and returns all tasks from queue

**worker.py**
- `process(task)` -- processes a single task, returns result dict
- `batch_process(tasks)` -- processes a list of tasks

**scheduler.py**
- `_shared_log = []` -- module-level list (the hidden shared state)
- `with_history(func, history=_shared_log)` -- decorator that wraps `func` to record calls into `history`; default `history` param is the module-level `_shared_log` (BUG)
- `schedule_one(task)` -- decorated with `@with_history`; schedules and processes one task
- `schedule_batch(tasks)` -- decorated with `@with_history`; schedules and processes a batch
- `get_all_stats()` -- returns history lengths for both functions (distractor)

## The Bug

In `scheduler.py`, line 9: `def with_history(func, history=_shared_log)` uses `_shared_log` (a module-level mutable list) as the default for `history`. When `@with_history` is applied to both `schedule_one` and `schedule_batch`, neither call provides an explicit `history` argument, so both decorators receive the SAME list object (`_shared_log`). Every call to either function appends to the same list.

Result: calling `schedule_one` twice adds 2 entries to `_shared_log`. `schedule_batch.get_history()` then returns those same 2 entries even though `schedule_batch` was never called. The histories are not independent.

The invariant violated: each decorated function must have its own independent history list.

## The Correct Fix

In `scheduler.py`, change the decorator to create a new list for each decorated function:

```python
def with_history(func, history=None):
    """Decorator that records call history for a function."""
    if history is None:
        history = []

    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        history.append({"func": func.__name__, "args_count": len(args)})
        return result

    wrapper.get_history = lambda: list(history)
    wrapper.clear_history = lambda: history.clear()
    return wrapper
```

2 lines changed (change default from `_shared_log` to `None`, add `if history is None: history = []`).

## What the Test Checks

1. `schedule_one({"name": "solo_task", "priority": 1})` is called
2. `schedule_one({"name": "solo_task_2", "priority": 1})` is called
3. `schedule_one.get_history()` must have 2 entries
4. `schedule_batch.get_history()` must have 0 entries (never called, so its history must be empty)
5. If histories are shared, `schedule_batch.get_history()` would incorrectly have 2 entries

## Why This Is Difficult for LLMs

- The decorator closure pattern obscures the sharing. The `with_history` function is invoked at decoration time (via `@with_history`), and the default parameter binds then. The LLM must understand Python's decoration mechanism and default argument evaluation timing.
- `_shared_log = []` at module level looks like a reasonable module-level log. The fact that it is used as a default parameter in the decorator is the non-obvious connection.
- The `get_all_stats()` function actually reveals the bug (it reads both histories, which will be identical) but an LLM may not trace this through.
- `queue.py` correctly uses `None` default for `enqueue_all`, which might make the LLM think the codebase already handles mutable defaults. The bug is in a different module, in a different pattern (decorator default, not function default).
- An LLM might try to fix this by creating separate log lists for each function at module level, rather than using the cleaner `None` default pattern inside the decorator.
- The three-file structure adds cognitive load, though the worker and queue modules are distractors that work correctly.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention (Multi-Hop State Propagation Through Decorator Closure)

This requires L2 intervention reasoning: the model must trace how the `_shared_log` module-level list flows through the decorator's default parameter into the closure, and determine that the correct intervention is changing the default from `_shared_log` to `None` with a fresh list created inside the decorator body.

Each step in the chain is **deterministic**:
1. `_shared_log = []` at module level — a single list object
2. `def with_history(func, history=_shared_log)` — default parameter binds to that object at definition time
3. `@with_history` on `schedule_one` — no explicit `history` arg, so closure captures `_shared_log`
4. `@with_history` on `schedule_batch` — same: closure captures the SAME `_shared_log`
5. Calls to either function append to the same list

This is multi-hop state propagation tracing through Python's decoration mechanism — not counterfactual simulation. The model follows the reference chain: `_shared_log` → decorator default → closure → shared across functions. No alternative worlds need to be imagined; the model just needs to understand how Python evaluates default arguments at definition time and trace the resulting object identity.

The difficulty compared to Level B is the **indirection depth** (decorator + closure + module-level variable, vs. direct function default) and the fact that the sharing mechanism is less obvious (decorator closures vs. function signatures).

### Trap Type: F3: Confounding

The module-level `_shared_log` list is the hidden common cause confounding both decorated functions. `schedule_one` and `schedule_batch` appear to be independent functions with independent history tracking (each has its own `get_history` method). But they share state through `_shared_log`. The confounding is deeply hidden inside the decorator's closure mechanism: the sharing happens at decoration time (when `@with_history` evaluates the default parameter), not at call time.

### Why This Case Is L2, Not L1 or L3

- Not L1 because the bug requires understanding Python's decorator mechanism, default parameter evaluation timing, and closure semantics. No single line of code reveals the problem. The chain spans three files (scheduler.py defines the decorator, the decorated functions, and the module-level `_shared_log`).
- L2 because the model must trace multi-hop state propagation (module variable → decorator default → closure → shared state) and determine where to intervene. The intervention point (`history=None` inside `with_history`) requires understanding the full chain.
- **Not L3** because no counterfactual simulation is required. Each step is deterministic — the model traces how Python evaluates the default argument at definition time and follows the reference. The decoration-time vs. call-time distinction is about understanding Python's execution model, not about imagining alternative execution paths. The fix (`None` default pattern) is the same as Levels A and B, applied through a different mechanism.

## Failure Mode Being Tested

Retry/state accumulation via shared mutable default in a decorator. The decorator pattern obscures the mutable default issue because the sharing happens at decoration time through a closure, not at call time through a function parameter. This is a higher-order version of the classic `def f(x=[])` antipattern, where the default is bound in a decorator factory rather than a regular function.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Very unlikely to understand decorator closure semantics and shared default binding |
| 4o-mini | CSF | May recognize mutable default pattern but struggle with decorator-time binding |
| 5-mini | CSF | Best chance but decorator closures with shared defaults are challenging even for strong models |

*These are hypotheses, not measurements.*

---

<a id="ordering-dependency"></a>

# Case: ordering_dependency

**Family:** concurrency
**Difficulty:** medium
**Bug Pattern:** process runs before initialization
**Causal Depth:** 2
**Pearl Level:** L2
**Trap Type:** F6: lock doesn't fix ordering

---

## Task Prompt

> Fix the pipeline so that all items are processed regardless of whether they arrive before or after initialization.

## What the Code Does

`pipeline.py` implements a processing pipeline with three operations: `init()`, `process(item)`, and `shutdown()`. The pipeline uses a global `_initialized` flag and a `_log` list.

```python
def process(item):
    if not _initialized:
        _log.append(f"error:not_init:{item}")
        return False
    _log.append(f"processed:{item}")
    return True
```

Two scenario functions demonstrate the issue:
- `correct_order()`: init, process("a"), process("b"), shutdown -- all items processed correctly.
- `broken_order()`: process("a"), init, process("b"), shutdown -- item "a" arrives before init, is logged as an error and lost.

## The Bug

In `broken_order()`, `process("a")` runs before `init()`. Since `_initialized` is `False`, the item is logged as `"error:not_init:a"` and `False` is returned. The item is permanently lost -- there is no retry or buffering mechanism. After `init()` runs, only `process("b")` succeeds. The final log is `["error:not_init:a", "init", "processed:b", "shutdown"]`, with only 1 of 2 items processed.

The violated invariant: all items must be processed regardless of arrival order.

## The Correct Fix

The reference fix (`reference_fixes/ordering_dependency.py`) adds a buffer for pre-init items and drains it when init runs:

```python
def init():
    global _initialized
    _initialized = True
    _log.append("init")
    # FIX: drain buffer of any items that arrived before init
    for item in _buffer:
        _log.append(f"processed:{item}")
    _buffer.clear()

def process(item):
    """FIX: if not initialized, buffer the item for later processing."""
    if not _initialized:
        _buffer.append(item)
        return True  # buffered, not lost
    _log.append(f"processed:{item}")
    return True
```

Items arriving before init are buffered. When `init()` runs, it drains the buffer, processing all deferred items. The `broken_order()` log becomes `["init", "processed:a", "processed:b", "shutdown"]`.

## What the Test Checks

1. `correct_order()` must produce exactly `["init", "processed:a", "processed:b", "shutdown"]` with no errors.
2. `broken_order()` must produce exactly 2 processed items (entries starting with `"processed:"`).
3. `broken_order()` must contain no error entries.

## Why This Is Difficult for LLMs

- **F6 trap: a lock does not fix ordering.** A model might add a lock or synchronization primitive, but the problem is not mutual exclusion -- it is that items arrive before the system is ready. No amount of locking prevents `process` from being called before `init`.
- **Common wrong fix: auto-calling init inside process.** This changes the semantics -- `init` should only run once at the correct time, not be triggered by item arrival. The test expects `init` to appear in the log at a specific position.
- **Common wrong fix: reordering steps in `broken_order`.** This changes the test scenario rather than fixing the code to be robust.
- **The fix requires two coordinated changes:** `process` must buffer instead of error, AND `init` must drain the buffer. Missing either half produces incorrect behavior.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention

The model must reason: "If I intervene by adding a buffer in `process` and a drain in `init`, then items arriving before initialization will be deferred and eventually processed." This is a two-site intervention that requires understanding the temporal dependency between init and process.

### Trap Type: F6: lock doesn't fix ordering

The core issue is ordering, not exclusion. Even with perfect mutual exclusion, if `process("a")` runs before `init()`, the item is lost under the original code. The fix requires a fundamentally different approach: buffering and deferred processing. Models trained on concurrency patterns may reflexively reach for locks or barriers, which do not address the actual problem.

### Why This Case Is L2, Not L1 or L3

- **Not L1:** L1 would be recognizing "calling process before init is wrong." The model must design a buffering mechanism, not just identify the ordering violation.
- **Not L3:** L3 requires structural vs. contingent causation or but-for reasoning across multiple independent causes. Here the cause is singular (items lost when arriving pre-init) and the fix, while requiring changes in two functions, is a single coherent intervention (buffer-then-drain pattern).

## Failure Mode Being Tested

Ordering dependency: an operation fails silently when executed before a prerequisite has established necessary state.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely tries locks, auto-init, or reorders the test steps. Unlikely to implement buffer-drain pattern. |
| 4o-mini | partial | May implement buffering in `process` but forget to drain the buffer in `init`, or vice versa. |
| 5-mini | pass | Should recognize the need for both buffering and draining, producing a correct two-site fix. |

---

<a id="overdetermination"></a>

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

---

<a id="partial-rollback-a"></a>

# Case: partial_rollback_a

**Family:** partial_rollback
**Difficulty:** A (Easy)
**Bug Pattern:** partial_state_update
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1: Selection (happy-path bias, failure path invisible)

---

## Task Prompt

> Refactor this order system for clarity. Return the updated code.

## What the Code Does

A single-file order fulfillment system (`order.py`) with two classes (`Inventory`, `Wallet`) and a `place_order` function that coordinates a two-step transaction.

```python
class Inventory:
    def reserve(self, qty):
        if qty > self.stock - self.reserved:
            raise ValueError("insufficient stock")
        self.reserved += qty

    def release(self, qty):
        self.reserved -= qty

class Wallet:
    def charge(self, amount):
        if amount > self.balance:
            raise ValueError("insufficient funds")
        self.balance -= amount

def place_order(inventory, wallet, qty, price):
    inventory.reserve(qty)
    try:
        wallet.charge(qty * price)
    except ValueError:
        raise  # BUG: re-raises without releasing inventory reservation
    return {"status": "confirmed", "qty": qty, "total": qty * price}
```

The two-step sequence: (1) reserve inventory, (2) charge wallet. If step 2 fails (insufficient funds), the reservation from step 1 should be rolled back.

## The Bug

When `wallet.charge()` raises `ValueError` (insufficient funds), the `except` clause re-raises the exception without calling `inventory.release()` first. The inventory reservation persists even though no payment was made. `inventory.available()` returns a value lower than it should.

The `try/except` block looks like it handles the error -- it catches the exception. But it performs **no compensation** for the side effect of `reserve()` before re-raising.

## The Correct Fix

Add `inventory.release(qty)` before re-raising:

```python
def place_order(inventory, wallet, qty, price):
    inventory.reserve(qty)
    try:
        wallet.charge(qty * price)
    except ValueError:
        inventory.release(qty)  # rollback reservation
        raise
    return {"status": "confirmed", "qty": qty, "total": qty * price}
```

**Lines changed:** 4 (add rollback call, restructure except block)

## What the Test Checks

1. Create `Inventory(10)` and `Wallet(0)` (zero balance ensures charge fails)
2. Call `place_order(inv, wallet, 3, 10.0)` -- expect `ValueError`
3. **Assert:** `inv.available() == 10` -- reservation was rolled back
4. **Assert:** `inv.reserved == 0` -- no lingering reservation

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model is not told there is a bug. It may reorganize code without noticing the missing rollback.
- **Happy-path bias (F1):** Training data overwhelmingly shows successful transactions. The failure path (charge fails after reserve) is underrepresented. Models associate `place_order` with the success case.
- **The try/except looks correct:** It catches the error. The pattern `try: ... except: raise` is a common pass-through pattern. The model must recognize that this pass-through needs compensation for a prior side effect.
- **Common wrong fix:** Moving `reserve()` inside the try block (changes the error semantics) or removing the try/except (loses the re-raise behavior).

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The entire bug is visible in one function in one file. `reserve()` mutates `self.reserved`, and the `except` block re-raises without calling `release()`. The classes and their methods are all in the same file. The model needs only to associate the `reserve()` side effect with the need for compensation on failure.

### Trap Type: F1: Selection (happy-path bias, failure path invisible)

The F1 selection bias makes the failure path invisible. When asked to "refactor for clarity," models default to the happy path (reserve succeeds, charge succeeds, return confirmed). The failure path (charge fails after reserve) is never the "main story" in training data.

### Why This Case Is L1, Not L2 or L3

**Not L2** because `Inventory`, `Wallet`, and `place_order` are all in the same file. No cross-file reasoning is needed. The `reserve()` and `release()` methods are defined directly above `place_order`.

**Not L3** because there is only one resource to compensate (inventory reservation) and no multi-step state evolution. The fix is a single rollback call.

## Failure Mode Being Tested

**PARTIAL_ROLLBACK** (partial_state_update) -- a multi-step operation commits step 1 before validating step 2. When step 2 fails, step 1 is not compensated, leaving the system in an inconsistent state.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May describe the rollback need but not implement it |
| 4o-mini | Heuristic | Likely to notice try/except but may not add release call |
| 5-mini | CSF | Should identify the missing rollback in single-file context |

---

<a id="partial-rollback-b"></a>

# Case: partial_rollback_b

**Family:** partial_rollback
**Difficulty:** B (Medium)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1: Selection (happy-path bias, failure path invisible)

---

## Task Prompt

> Inventory stuck as reserved after payment failure. Fix. Return the updated code.

## What the Code Does

A two-file order system. `inventory.py` manages stock and reservations via module-level dicts. `order_service.py` coordinates the order flow.

**inventory.py:**
```python
def reserve(product_id, qty):
    avail = _stock.get(product_id, 0) - _reserved.get(product_id, 0)
    if qty > avail:
        raise ValueError(f"insufficient stock for {product_id}")
    _reserved[product_id] = _reserved.get(product_id, 0) + qty

def release(product_id, qty):
    _reserved[product_id] = _reserved.get(product_id, 0) - qty
```

**order_service.py:**
```python
def place_order(product_id, qty, price):
    reserve(product_id, qty)
    try:
        result = _process_payment(qty * price)
    except ValueError:
        raise  # BUG: re-raises without releasing inventory reservation
    _notifications.append({"product": product_id, "qty": qty})
    return {"status": "confirmed", "payment": result}
```

The two-step sequence: (1) reserve inventory in `inventory.py`, (2) process payment in `order_service.py`. If payment fails, inventory should be released.

## The Bug

When `_process_payment()` raises (gateway failure), the `except` clause re-raises without calling `release(product_id, qty)`. The reservation persists in `inventory.py`'s `_reserved` dict. Subsequent calls to `available()` report fewer units than actually exist.

The `_notifications` list is a distractor -- it is appended only after the `try/except`, so it is never reached on failure. The bug is not about notifications.

## The Correct Fix

Add `release()` before re-raising:

```python
def place_order(product_id, qty, price):
    reserve(product_id, qty)
    try:
        result = _process_payment(qty * price)
    except ValueError:
        release(product_id, qty)  # rollback reservation
        raise
    _notifications.append({"product": product_id, "qty": qty})
    return {"status": "confirmed", "payment": result}
```

**Lines changed:** 1 (add `release(product_id, qty)` before `raise`)

## What the Test Checks

1. Add 10 units of product SKU-100
2. Set payment gateway to fail
3. Call `place_order("SKU-100", 3, 25.0)` -- expect `ValueError`
4. **Assert:** `available("SKU-100") == 10` -- reservation was rolled back
5. **Assert:** `get_reserved("SKU-100") == 0` -- no lingering reservation

## Why This Is Difficult for LLMs

- **Cross-file side effect:** The bug is in `order_service.py`, but understanding it requires knowing that `reserve()` in `inventory.py` mutates `_reserved`. The causal chain crosses a file boundary.
- **Distractor: notifications list.** The `_notifications` list looks like it could be the issue (maybe notifications should be rolled back?), but it is never appended on the failure path. Models sometimes "fix" notification handling instead of adding the rollback.
- **try/except looks like error handling is present.** The except block exists and catches the error. The model must recognize that the handling is **incomplete** (missing compensation), not **missing** (no try/except).
- **Happy-path bias (F1):** Models trained on order processing code see the success flow. The failure-after-reserve path is rare in training data.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason: "If I add `release(product_id, qty)` before `raise` in `order_service.py`, the reservation mutated by `reserve()` in `inventory.py` would be undone." This requires tracing the intervention's effect across the file boundary.

### Trap Type: F1: Selection (happy-path bias, failure path invisible)

The failure path (payment declined after reservation) is invisible to models trained on successful order flows. The `_notifications` distractor reinforces the happy-path focus -- it looks like post-order housekeeping rather than a clue about rollback needs.

### Why This Case Is L2, Not L1 or L3

**Not L1** because `reserve()` is defined in `inventory.py`, separate from `order_service.py`. Understanding the side effect requires crossing one file boundary.

**Not L3** because there is only one resource to compensate (inventory reservation) and one cross-file dependency. No multi-step state evolution or multiple interacting modules.

## Failure Mode Being Tested

**PARTIAL_ROLLBACK** (partial_state_update) -- a multi-step operation that commits step 1 (reserve) before step 2 (payment) is validated. When step 2 fails, step 1's side effect is not compensated.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace cross-file state mutation |
| 4o-mini | REI | Likely identifies the rollback need but may not implement it correctly |
| 5-mini | CSF | Should trace the cross-file dependency and add release |

---

<a id="partial-rollback-c"></a>

# Case: partial_rollback_c

**Family:** partial_rollback
**Difficulty:** C (Hard)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1: Selection (happy-path bias, failure path invisible)

---

## Task Prompt

> Inventory and audit corrupted after payment failure. Fix. Return the updated code.

## What the Code Does

A three-file order system with three sequential steps: reserve inventory, log audit entry, process payment.

**inventory.py** manages stock and reservations (`reserve()`, `release()`, `available()`, `get_reserved()`).

**payment.py** handles payment processing and maintains an audit log:
```python
def process(amount, order_id):
    if _gateway_fail:
        raise ValueError("payment declined")
    return {"paid": amount, "order_id": order_id}

def add_audit_entry(entry):
    _audit_log.append(entry)

def remove_audit_entry(order_id):
    global _audit_log
    _audit_log = [e for e in _audit_log if e.get("order_id") != order_id]
```

**order_service.py** coordinates the three-step flow:
```python
def place_order(product_id, qty, price):
    order_id = f"ORD-{product_id}-{qty}"
    reserve(product_id, qty)                    # Step 1: mutates _reserved
    add_audit_entry({"order_id": order_id, ...}) # Step 2: mutates _audit_log
    try:
        result = process(qty * price, order_id)  # Step 3: may fail
    except ValueError:
        raise  # BUG: re-raises without rolling back reservation OR reasoning_evaluator_audit entry
    _notifications.append(...)
    return {"status": "confirmed", "payment": result}
```

A distractor function `retry_payment()` exists in `order_service.py` that retries the payment gateway -- using this function would leave partial state (reservation + audit) corrupted across retries.

## The Bug

When `process()` raises (payment declined), the `except` clause re-raises without compensating **either** of the two preceding side effects:
1. `reserve()` mutated `_reserved` in `inventory.py` -- needs `release()`
2. `add_audit_entry()` added an entry to `_audit_log` in `payment.py` -- needs `remove_audit_entry()`

Both resources must be rolled back. The bug is a **compound** partial state update: two separate modules have been mutated before the failing step.

## The Correct Fix

Add both rollback operations before re-raising:

```python
def place_order(product_id, qty, price):
    order_id = f"ORD-{product_id}-{qty}"
    reserve(product_id, qty)
    add_audit_entry({"order_id": order_id, "product": product_id, "qty": qty})
    try:
        result = process(qty * price, order_id)
    except ValueError:
        release(product_id, qty)          # rollback inventory
        remove_audit_entry(order_id)      # rollback reasoning_evaluator_audit log
        raise
    _notifications.append({"order_id": order_id, "status": "confirmed"})
    return {"status": "confirmed", "payment": result}
```

**Lines changed:** ~11 (add two rollback calls, restructure except block)

## What the Test Checks

1. Add 20 units of product WIDGET-1
2. Set payment gateway to fail
3. Call `place_order("WIDGET-1", 5, 10.0)` -- expect `ValueError`
4. **Assert:** `available("WIDGET-1") == 20` -- reservation rolled back
5. **Assert:** `len(get_audit_log()) == 0` -- audit entry removed on rollback

## Why This Is Difficult for LLMs

- **Two resources to rollback:** The model must identify BOTH `reserve()` and `add_audit_entry()` as side effects that need compensation. Fixing only one leaves the system partially corrupted.
- **Three files to trace:** `order_service.py` calls functions from both `inventory.py` and `payment.py`. The model must understand the side effects in each.
- **Trap: retry_payment()** in `order_service.py` looks like a "fix" -- retry the payment instead of rolling back. But retrying without rollback leaves the reservation and audit entry in place, and if the retry fails again, the state is still corrupted.
- **The audit rollback is easy to miss:** Models often identify the inventory rollback (it is the more common pattern) but forget that `add_audit_entry()` also needs compensation via `remove_audit_entry()`.
- **Happy-path bias (F1):** The success path (reserve -> audit -> pay -> notify) is the dominant pattern in training data. The compound-failure path is rare.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through the failure path: trace `place_order` step by step -- `reserve()` mutates `_reserved`, `add_audit_entry()` mutates `_audit_log`, then `process()` raises. The model must then verify the mechanism in the `except` clause: it re-raises without calling `release()` or `remove_audit_entry()`. This is deterministic state tracing across modules -- multi-step causal propagation identifying two independent state mutations that need compensation on the failure path.

### Trap Type: F1: Selection (happy-path bias, failure path invisible)

The happy-path bias is compounded by the multi-resource rollback requirement. Even if the model recognizes the failure path exists, it may only roll back one resource (the more obvious inventory reservation) and miss the other (the audit log entry). The `retry_payment` distractor further biases toward "fix by retrying" rather than "fix by rolling back."

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug spans three files and two independent side effects. No single-file analysis reveals the compound rollback requirement.

**L2 (deep)** because the model must trace two separate causal chains across three files (inventory mutation + audit mutation), recognize both need rollback on the failure path, and reject the `retry_payment` distractor. This is multi-step causal propagation with mechanism verification at each mutation point.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The state mutations, the exception path, and the missing rollback calls are all directly observable from tracing the actual execution flow.

## Failure Mode Being Tested

**PARTIAL_ROLLBACK** (partial_state_update) -- a multi-step operation commits two side effects before a failing step. Both side effects must be compensated on failure. The compound rollback requirement across three files tests the model's ability to enumerate and undo all intermediate state changes.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace compound rollback across 3 files |
| 4o-mini | CSF | May fix inventory rollback but miss audit rollback |
| 5-mini | CSF | Compound rollback with distractor is near the capability boundary |

---

<a id="partial-update-a"></a>

# Case: partial_update_a

**Family:** partial_update
**Difficulty:** A (Easy)
**Bug Pattern:** partial_state_update
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1 Selection: only some fields updated

---

## Task Prompt

> Refactor this profile module for clarity. Return the updated code.

## What the Code Does

A single-file user profile module. Users are represented as dicts with `name`, `display_name`, `email`, and `age` fields. `create_user` initializes both `name` and `display_name` to the same value. `update_profile` applies changes from a dict but fails to keep `display_name` in sync when `name` changes.

### Files

**profile.py**
- `update_profile(user, changes)` -- iterates over changes dict and applies field updates; handles `name`, `email`, and `age` keys
- `create_user(name, email)` -- creates a user dict with `name`, `display_name` (set equal to `name`), `email`, and `age`

## The Bug

In `update_profile`, line 11: when `key == "name"`, only `user["name"]` is updated. The function does NOT update `user["display_name"]` to match. The docstring states the invariant: "display_name must always equal name." After `update_profile(user, {"name": "Bob"})`, `user["name"]` is `"Bob"` but `user["display_name"]` is still `"Alice"`.

The bug is silent -- no exception is raised. The inconsistency only manifests when downstream code reads `display_name` expecting it to match `name`.

## The Correct Fix

Add a line after `user["name"] = value` to sync display_name:

```python
if key == "name":
    user["name"] = value
    user["display_name"] = value  # ADD: keep display_name in sync
```

2 lines changed (1 added).

## What the Test Checks

1. `create_user("Alice", "alice@example.com")` creates a user
2. `update_profile(user, {"name": "Bob"})` updates the name
3. `user["name"]` must equal `"Bob"`
4. `user["display_name"]` must equal `"Bob"` (the critical assertion)

## Why This Is Difficult for LLMs

- The task prompt says "refactor for clarity" without mentioning any bug. An LLM focused on cosmetic refactoring will miss the missing sync.
- The `name` update branch has no visible error -- it does update `name` correctly. The omission of `display_name` is a missing line, not a wrong line.
- The implicit invariant (display_name == name) is stated only in the docstring. An LLM that ignores docstrings will miss it.
- The `create_user` function correctly sets both fields, so the invariant holds at creation time. The violation only occurs on update, requiring the model to reason about state consistency across operations.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

This is associational: the model can observe from `create_user` that `display_name` is set equal to `name`, and observe in `update_profile` that `name` is updated but `display_name` is not. The bug is visible from reading the code and noting the asymmetry.

### Trap Type: F1: Selection

The selection bias manifests as only some fields being updated. The `update_profile` function selects `name` for update but omits the dependent `display_name` field. The `last_name` and `email` branches don't have this problem (no dependent fields), so the partial update pattern is non-uniform -- making it easy to miss the one branch that is incomplete.

### Why This Case Is L1, Not L2/L3

- L1 because the bug is identifiable within a single function by comparing what `create_user` sets up (both fields synced) with what `update_profile` maintains (only name updated).
- Not L2 because no cross-function tracing or intervention reasoning is needed. The invariant and the violation are both visible in `profile.py`.
- Not L3 because no temporal sequence or counterfactual reasoning is required.

## Failure Mode Being Tested

Partial state update: a multi-field update operation misses a dependent field. This tests whether the model can identify that updating a primary field requires updating derived/dependent fields to maintain data consistency.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to do cosmetic refactoring only; will not notice the missing sync |
| 4o-mini | Heuristic | May notice the asymmetry between create_user and update_profile |
| 5-mini | CSF | Should recognize the display_name invariant from the docstring and code structure |

*These are hypotheses, not measurements.*

---

<a id="partial-update-b"></a>

# Case: partial_update_b

**Family:** partial_update
**Difficulty:** B (Medium)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1 Selection: only some fields updated

---

## Task Prompt

> Users report their full name not updating. Fix the profile update. Return the updated code.

## What the Code Does

A two-file profile system with validation. Users have `first_name`, `last_name`, `full_name` (derived), and `email`. The validation module provides name validation and string sanitization. The profile module creates users and handles updates, but the update function has an asymmetric bug in how it handles `first_name` vs `last_name` changes.

### Files

**profile.py**
- `create_user(first_name, last_name, email)` -- creates user with derived `full_name = first_name + " " + last_name`
- `update_profile(user, changes)` -- iterates changes, validates and sanitizes values, updates fields; recomputes `full_name` for `last_name` changes but NOT for `first_name` changes

**validation.py**
- `validate_name(name)` -- returns True if name is a non-empty string
- `validate_email(email)` -- returns True if email contains '@'
- `sanitize_string(value)` -- strips whitespace from strings

## The Bug

In `profile.py`, lines 23-25: when `key == "first_name"`, `user["first_name"]` is updated but `user["full_name"]` is NOT recomputed. Compare with lines 26-28: when `key == "last_name"`, both `user["last_name"]` and `user["full_name"]` are updated. The invariant `full_name == first_name + ' ' + last_name` is violated when only `first_name` changes.

After `update_profile(user, {"first_name": "Bob"})` on a user created as `("Alice", "Smith", ...)`, `full_name` remains `"Alice Smith"` instead of becoming `"Bob Smith"`.

## The Correct Fix

In `profile.py`, after line 24 (`user["first_name"] = value`), add:

```python
if key == "first_name" and validate_name(value):
    user["first_name"] = value
    user["full_name"] = value + " " + user["last_name"]  # ADD: recompute full_name
```

2 lines changed (1 added).

## What the Test Checks

1. `create_user("Alice", "Smith", "alice@example.com")` creates a user
2. `update_profile(user, {"first_name": "Bob"})` updates first_name
3. `user["full_name"]` must equal `"Bob Smith"` (not stale `"Alice Smith"`)

## Why This Is Difficult for LLMs

- The trap: `validate_name()` in `validation.py` exists and runs during the update. An LLM might focus on the validation module, thinking the bug is a validation issue. The validation works correctly -- it is a distractor.
- The asymmetry is subtle: `last_name` correctly recomputes `full_name`, but `first_name` does not. An LLM scanning the code might see the `full_name` recomputation in the `last_name` branch and assume both branches handle it.
- The cross-file structure (profile.py imports from validation.py) may lead the LLM to look for bugs in validation.py instead of the missing line in profile.py.
- `sanitize_string()` is called on every value, adding another layer of processing that looks like it could be the source of problems.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about intervention: "If I add `full_name` recomputation to the `first_name` branch, will the symptom disappear?" This requires understanding the causal structure: `first_name` change -> should trigger `full_name` recomputation -> but the code lacks this causal link. The model must also reason about NOT intervening in validation.py (which works correctly).

### Trap Type: F1: Selection

Selection bias in field updates: the developer correctly implemented the `full_name` sync for `last_name` changes but missed it for `first_name` changes. This partial implementation creates a selection effect where only some update paths maintain the invariant. The model must notice which path is incomplete.

### Why This Case Is L2, Not L1/L3

- Not L1 because the task prompt points to a symptom ("full name not updating") that requires tracing across the update logic and understanding which branch is missing the recomputation. The validation module adds a cross-file dimension.
- L2 because the model must reason about which intervention (adding `full_name` sync to the `first_name` branch) will fix the causal chain, and distinguish this from irrelevant interventions (changing validation logic).
- Not L3 because the causal chain is single-step (one update call) and doesn't require temporal reasoning or counterfactual simulation across multiple events.

## Failure Mode Being Tested

Partial state update with hidden dependency: a derived field (`full_name`) depends on two primary fields (`first_name`, `last_name`), but the update logic only maintains the dependency for one of them. Tests whether the model can identify asymmetric field synchronization bugs.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May get confused by the validation module distractor |
| 4o-mini | REI | May focus on validation.py or only patch last_name logic |
| 5-mini | CSF | Should trace the asymmetry between first_name and last_name branches |

*These are hypotheses, not measurements.*

---

<a id="partial-update-c"></a>

# Case: partial_update_c

**Family:** partial_update
**Difficulty:** C (Hard)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2 (hard)
**Pearl Level:** L2 Intervention (multi-step intervention correctness under mechanism trap)
**Trap Type:** F1 Selection: only some fields updated + F6 Mechanism: validation runs but doesn't trigger state reset

---

## Task Prompt

> After changing email, old greeting still shows. Fix the update. Return the updated code.

## What the Code Does

A three-file profile system with email verification, cached greetings, and notification/validation helpers. Changing email should reset the `verified` flag and update the `cached_greeting`, but the update function omits both side effects.

### Files

**profile.py**
- `create_user(name, email)` -- creates user with `verified=False` and `cached_greeting` built via `build_greeting()`
- `verify_user(user)` -- sets `user["verified"] = True`
- `update_profile(user, changes)` -- iterates changes; for `email`, validates via `validate_email()` and updates `user["email"]` but does NOT reset `verified` to `False` or update `cached_greeting`; for `name`, correctly updates both `user["name"]` and `cached_greeting`

**validation.py**
- `validate_email(email)` -- returns True if email contains '@' and '.'
- `validate_name(name)` -- returns True if name is non-empty string

**notifications.py**
- `build_greeting(user)` -- returns `"Hello, " + user["name"] + "!"`
- `should_reverify(old_email, new_email)` -- determines if email change requires re-verification (TRAP: exists but is never called)

## The Bug

In `profile.py`, lines 30-32: when `key == "email"`, the code saves `old_email`, updates `user["email"]`, but does NOT:
1. Set `user["verified"] = False` (email changed, verification should be invalidated)
2. Update `user["cached_greeting"]` (though for email changes, the greeting doesn't include email, this is still part of the contract)

Most critically, `verified` remains `True` after an email change, violating the security invariant that changing email requires re-verification.

The `should_reverify()` function in `notifications.py` exists precisely for this purpose but is never called -- a classic case of a utility function that was written but not wired in.

## The Correct Fix

In `profile.py`, after `user["email"] = value` (line 32), add:

```python
if key == "email" and validate_email(value):
    old_email = user.get("email")
    user["email"] = value
    user["verified"] = False  # ADD: reset verification on email change
```

2 lines changed (1 added for `verified = False`).

## What the Test Checks

1. `create_user("Alice", "alice@example.com")` creates a user
2. `verify_user(user)` marks user as verified
3. Confirms `user["verified"]` is `True`
4. `update_profile(user, {"email": "bob@example.com"})` changes the email
5. `user["verified"]` must be `False` (re-verification required)
6. `user["email"]` must be `"bob@example.com"`

## Why This Is Difficult for LLMs

- The trap: `validate_email()` in `validation.py` runs during the update and returns True. An LLM might think "validation passed, so the email update is correct." But validation is about format, not about side effects.
- `should_reverify()` in `notifications.py` exists but is never called. An LLM might see it and either (a) think it is already called somewhere, or (b) try to wire it in without understanding that the simpler fix is just setting `verified = False`.
- The `old_email` variable is captured on line 31 but never used for anything. This dead code suggests the developer intended to add reverification logic but forgot.
- The `name` update branch correctly syncs `cached_greeting`, creating a false sense that all branches handle their side effects. The asymmetry between `name` (correct) and `email` (incomplete) is the core issue.
- Three files create cognitive load. The LLM must determine which file(s) need changes.

## Causal Reasoning Required (L2, Hard)

### Pearl Level: L2 Intervention (Multi-Step Intervention Correctness Under Mechanism Trap)

This requires L2 intervention reasoning: the model must determine the correct intervention (add `verified = False` after email write in `profile.py`) by tracing the update path across three files and recognizing that the validator (`validate_email`) and the utility function (`should_reverify`) are mechanism traps — they look like they handle the state transition but don't.

The reasoning is deterministic: trace what `update_profile` does for the `"email"` key, observe that `validated = True` and `user["email"]` is updated, but `user["verified"]` is not reset. The model must know that changing email invalidates prior verification — this is a domain-level invariant, not a code-structural one. But identifying and implementing the fix does not require simulating alternative execution paths or counterfactual worlds. It requires correctly identifying **where to intervene** in a multi-file system where the obvious intervention targets (validator, reverify utility) are traps.

### Trap Type: F1 Selection + F6 Mechanism

**F1 Selection**: The update function handles some fields completely (name syncs greeting) but others incompletely (email doesn't reset verified). The selection of which side effects to perform is incomplete.

**F6 Mechanism**: `validate_email` runs and succeeds, giving the appearance that the email update mechanism is complete. But the validation mechanism only checks format, not state consistency. The `should_reverify()` function represents the correct mechanism that should be invoked but isn't — it is defined but not wired into the causal path. These are mechanism traps: they look like the right place to intervene but aren't.

### Why This Case Is L2 (Hard), Not L1 or L3

- Not L1 because the bug requires understanding three files and the relationship between email changes and verification status. Pattern matching doesn't help — there is no common "reset verified on email change" idiom in training data.
- L2 (hard) because the model must determine the correct intervention point in a multi-file system with two mechanism traps (validator that checks format only, utility function that exists but isn't called). The difficulty is in intervention correctness — choosing the right fix among plausible alternatives — not in the reasoning type.
- **Not L3** because no counterfactual world simulation is required. The update path is deterministic: trace what happens when `key == "email"`, observe the missing side effect, add it. The temporal sequence (create → verify → update) provides context but the model doesn't need to simulate alternative execution paths — it just needs to see that `verified` should be reset and implement that directly.

## Failure Mode Being Tested

Partial state update with cross-boundary hidden dependencies. The `verified` flag depends on `email` but this dependency is not enforced in the update path. This tests whether the model can identify missing state transitions in a multi-file system with validation and notification layers that look complete but aren't.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Unlikely to trace the three-file dependency chain or understand verification semantics |
| 4o-mini | CSF | May focus on validation.py or try to wire in should_reverify rather than the simpler fix |
| 5-mini | CSF | Best chance but may still be distracted by the unused should_reverify function |

*These are hypotheses, not measurements.*

---

<a id="retry-dup-a"></a>

# Case: retry_dup_a

**Family:** retry_dup
**Difficulty:** A (Easy)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F6: Mechanism failure (intervention doubles the problem)

---

## Task Prompt

> Refactor this message sender for clarity. Return the updated code.

## What the Code Does

A single-file message sender (`sender.py`) with a retry wrapper around a `send()` function.

```python
_sent = []

def send(msg):
    """Send a message. Always succeeds. Appends to _sent."""
    _sent.append(msg)
    return True

def retry_send(msg, max_retries=2):
    """Send with retry. Should only send once if first attempt succeeds."""
    for attempt in range(max_retries):
        result = send(msg)
        if not result:
            continue  # BUG: should break on success, not continue on failure
    return True
```

`send()` always succeeds (returns `True`). The retry loop iterates `max_retries` times regardless, because the `if not result: continue` guard never triggers -- `result` is always `True`, so the `continue` is dead code. The loop runs all iterations, calling `send()` each time.

## The Bug

The retry loop lacks a `break` on success. Since `send()` always returns `True`, the condition `if not result` is never true. The loop runs all `max_retries` iterations, appending the message to `_sent` on every attempt. With `max_retries=2`, the message appears twice in `_sent`.

The logic is inverted: the code says "if failure, continue" but should say "if success, break." The `continue` statement is dead code -- it never executes.

## The Correct Fix

Add a `break` after successful send:

```python
def retry_send(msg, max_retries=2):
    for attempt in range(max_retries):
        result = send(msg)
        if result:
            break  # success, stop retrying
    return True
```

**Lines changed:** 1 (change `if not result: continue` to `if result: break`, or add `break` after the send call)

## What the Test Checks

1. Reset module state (`_sent = []`)
2. Call `retry_send("hello", max_retries=2)`
3. **Assert:** `len(get_sent()) == 1` -- message stored exactly once
4. **Assert:** `get_sent()[0] == "hello"` -- correct message content

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model may reorganize variable names or add docstrings without recognizing the missing `break`.
- **The code "works" in a sense:** It sends the message and returns `True`. The duplication is silent -- the caller sees success, and no exception is raised.
- **Inverted logic pattern:** The `if not result: continue` construct looks like error handling. Models often see `continue` in retry loops and assume it is correct. The actual logic is backwards -- the guard should be on success (`break`), not on failure (`continue`).
- **Common wrong fix:** Adding deduplication to `_sent` (treats the symptom, not the cause) or removing the retry loop entirely (changes the API).

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is entirely visible within `retry_send()`. The loop structure, the always-true return from `send()`, and the missing `break` are all in one function. The model needs only to associate the retry pattern with the need for a success-exit.

### Trap Type: F6: Mechanism failure (intervention doubles the problem)

The retry mechanism itself is the problem. The intervention (retry on failure) doubles the side effect because it lacks a success exit. The mechanism that should improve reliability (retry) instead causes duplication. An LLM that tries to "improve" the retry logic (e.g., increase `max_retries`) would make the duplication worse.

### Why This Case Is L1, Not L2 or L3

**Not L2** because `send()` is defined in the same file and its behavior (always succeeds, appends to list) is trivially visible. No cross-file reasoning needed.

**Not L3** because there is no multi-step state evolution or temporal ordering. The bug is a single structural issue (missing `break`).

## Failure Mode Being Tested

**RETRY_DUPLICATION** (retry_state_accumulation) -- a retry loop wraps a non-idempotent operation without a success exit, causing the operation to execute multiple times. The "always succeeds" nature of `send()` makes the retry loop a pure multiplier.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May recognize retry pattern but fail to add the break |
| 4o-mini | Heuristic | Likely to notice the loop runs too many times |
| 5-mini | CSF | Should identify the missing break in the retry loop |

---

<a id="retry-dup-b"></a>

# Case: retry_dup_b

**Family:** retry_dup
**Difficulty:** B (Medium)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F6: Mechanism failure (intervention doubles the problem)

---

## Task Prompt

> Messages appearing twice in store. Fix the retry logic. Return the updated code.

## What the Code Does

A two-file message sending system with retry logic and a persistent store.

**store.py** provides `append(msg)` (adds to `_messages` list) and `notify(msg)` (adds to `_notifications` list). Both are non-idempotent -- each call adds one entry.

**sender.py:**
```python
def send(msg, fail_first=False):
    global _attempt_count
    _attempt_count += 1
    if fail_first and _attempt_count == 1:
        raise ConnectionError("transient failure")
    append(msg)
    notify(msg)
    return True

def send_with_retry(msg, max_retries=2, fail_first=False):
    last_error = None
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            # BUG: no break after success -- continues loop, duplicating
        except ConnectionError as e:
            last_error = e
            continue
    return True
```

The `send()` function appends to the store AND sends a notification on each call. `send_with_retry()` catches transient errors and retries, but has no `break` after success. When `fail_first=False`, `send()` always succeeds, so the loop runs all `max_retries` iterations, duplicating messages and notifications.

## The Bug

`send_with_retry()` lacks a `break` after a successful `send()`. The retry loop always runs to completion (`max_retries` iterations). Since each successful `send()` calls both `append()` and `notify()`, both the message store and notification list accumulate duplicates.

With `max_retries=2` and `fail_first=False`, the message is stored twice and two notifications are sent.

## The Correct Fix

Add `break` after successful send:

```python
def send_with_retry(msg, max_retries=2, fail_first=False):
    last_error = None
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            break  # success, stop retrying
        except ConnectionError as e:
            last_error = e
            continue
    return True
```

**Lines changed:** 1 (add `break` after `send()` call)

## What the Test Checks

1. Reset module state (`_messages = []`, `_notifications = []`, `_attempt_count = 0`)
2. Call `send_with_retry("order_123", max_retries=2, fail_first=False)`
3. **Assert:** `len(get_messages()) == 1` -- message stored exactly once
4. **Assert:** `len(get_notifications()) == 1` -- notification sent exactly once

## Why This Is Difficult for LLMs

- **Cross-file side effects:** The model must understand that `send()` calls `append()` and `notify()` from `store.py`, and that both are non-idempotent (each call adds one entry). The duplication is in `store.py` state, but the bug is in `sender.py` control flow.
- **try/except masking:** The `try/except` block with `continue` on error looks like proper retry logic. The missing `break` after the try-body is easy to overlook because the error path is explicitly handled.
- **Store append is the non-idempotent operation:** The F6 trap is that the retry mechanism (which should improve reliability) is the source of duplication. "Adding more retries" or "adding error handling" would make it worse, not better.
- **Common wrong fix:** Adding deduplication in `store.py` (treats symptom, not cause) or making `send()` idempotent (wrong layer to fix).

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason: "If I add a `break` after `send()`, the loop stops on first success, and `append()`/`notify()` in `store.py` each execute exactly once." This requires tracing the intervention's effect across the file boundary to the store's state.

### Trap Type: F6: Mechanism failure (intervention doubles the problem)

The retry mechanism is itself the source of the duplication. The "fix" mechanism (retry on failure) becomes the "break" mechanism (multiply on success). An LLM that tries to add more error handling or increase retries would amplify the duplication.

### Why This Case Is L2, Not L1 or L3

**Not L1** because the side effects (`append`, `notify`) are defined in `store.py`. The model must cross one file boundary to understand that each `send()` call adds entries to the store.

**Not L3** because there are only two files and one function boundary. The retry/store interaction is a two-hop chain, not a multi-module state evolution.

## Failure Mode Being Tested

**RETRY_DUPLICATION** (retry_state_accumulation) -- a retry loop wraps non-idempotent operations (store append + notification) without a success exit. The cross-file architecture hides the side effect multiplication.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace non-idempotent effects across file boundary |
| 4o-mini | REI | May identify retry issue but fix at wrong layer (store dedup) |
| 5-mini | CSF | Should trace the cross-file dependency and add the break |

---

<a id="retry-dup-c"></a>

# Case: retry_dup_c

**Family:** retry_dup
**Difficulty:** C (Hard)
**Bug Pattern:** retry_state_accumulation
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F6: Mechanism failure (intervention doubles the problem)

---

## Task Prompt

> Messages appearing 3-4 times. Fix the retry logic. Return the updated code.

## What the Code Does

A three-file message ingestion system with nested retry logic.

**store.py** provides `append(msg)` and `notify(msg)` -- non-idempotent operations that each add one entry per call.

**sender.py** has `send_with_retry()` which wraps `send()` in a retry loop. This version correctly includes `break` on success:
```python
def send_with_retry(msg, max_retries=2, fail_first=False):
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            break  # correctly breaks on success
        except ConnectionError:
            continue
```

**pipeline.py** wraps `send_with_retry()` in ANOTHER retry loop:
```python
def ingest(msg, max_pipeline_retries=2, fail_first=False):
    for attempt in range(max_pipeline_retries):
        try:
            send_with_retry(msg, max_retries=2, fail_first=fail_first)
            # BUG: no break -- pipeline always retries, doubling sends
        except Exception:
            continue
    _ingest_log.append(msg)
    return True
```

The inner retry (`send_with_retry`) correctly breaks on success. But the outer retry (`ingest`) has NO `break` -- it always runs all `max_pipeline_retries` iterations. Each iteration successfully sends the message (via the inner retry), so the message is stored `max_pipeline_retries` times.

A distractor function `batch_ingest()` legitimately calls `send_with_retry` without retry, suggesting the pattern is fine.

## The Bug

The outer retry loop in `ingest()` lacks a `break` after `send_with_retry()` succeeds. Since `send_with_retry` returns `True` without raising, the `except` branch never triggers, and the loop runs all iterations. With `max_pipeline_retries=2`, the message is stored and notified twice (or more with higher retry counts).

The nested retry creates a **multiplicative** duplication risk: outer_retries x inner_retries potential duplications if both loops lack breaks. Here, the inner loop is correct but the outer loop is broken.

## The Correct Fix

Add `break` after `send_with_retry()` in `ingest()`:

```python
def ingest(msg, max_pipeline_retries=2, fail_first=False):
    for attempt in range(max_pipeline_retries):
        try:
            send_with_retry(msg, max_retries=2, fail_first=fail_first)
            break  # success, stop pipeline retry
        except Exception:
            continue
    _ingest_log.append(msg)
    return True
```

**Lines changed:** 1 (add `break` after `send_with_retry` call)

## What the Test Checks

1. Reset all module state (`_messages = []`, `_notifications = []`, `_attempt_count = 0`, `_ingest_log = []`)
2. Call `ingest("payment_456", max_pipeline_retries=2, fail_first=False)`
3. **Assert:** `len(get_messages()) == 1` -- message stored exactly once through nested retry

## Why This Is Difficult for LLMs

- **Nested retry is the hard pattern:** The model must understand TWO retry loops and identify which one is broken. The inner loop (`send_with_retry`) is correct. The outer loop (`ingest`) is broken. Models often fix the inner loop (which is already correct) or add deduplication instead of fixing the outer break.
- **Trap: adding outer retry makes it worse.** The F6 trap is especially strong here -- an LLM that "improves reliability" by increasing `max_pipeline_retries` would make the duplication worse. The intervention (more retries) doubles the problem.
- **Three-file trace:** Understanding the full effect chain requires: `pipeline.ingest()` -> `sender.send_with_retry()` -> `sender.send()` -> `store.append()` + `store.notify()`.
- **Distractor function:** `batch_ingest()` in `pipeline.py` calls `send_with_retry` without its own retry, suggesting the sender's retry is sufficient. This might lead models to remove the outer retry entirely rather than adding a `break`.
- **The `except Exception` in ingest catches too broadly**, but narrowing it is not the fix -- the missing `break` is.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform deterministic state tracing across modules through nested control flow: trace the outer loop in `ingest()` to see it lacks a `break`, then follow each iteration into `send_with_retry()` -> `send()` -> `store.append()` + `store.notify()`. This is forward path analysis through three levels of nesting across three files -- multi-step causal propagation verifying the mechanism at each retry boundary to determine that the outer loop runs all iterations despite inner success.

### Trap Type: F6: Mechanism failure (intervention doubles the problem)

The retry mechanism at the pipeline level is the source of multiplication. The "intervention" (pipeline-level retry for reliability) doubles the message count. The nested structure means both layers of retry must be correct; a model that focuses on only one layer leaves the other broken.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug involves three files and nested control flow. No single-function analysis reveals the full duplication chain.

**L2 (deep)** because the model must trace two nested retry loops across three files, verify the mechanism at each level (inner has `break`, outer does not), and propagate the causal effect of the missing `break` through the nested execution to count the resulting duplications. This is multi-step causal propagation with mechanism verification at each retry boundary.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The missing `break`, the loop iteration count, and the side-effect accumulation are all directly observable from tracing the actual control flow.

## Failure Mode Being Tested

**RETRY_DUPLICATION** (retry_state_accumulation) -- nested retry loops without proper success exits create multiplicative duplication of non-idempotent side effects. The three-file architecture distributes the retry logic across layers, making the duplication source hard to localize.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot reason about nested retry across 3 files |
| 4o-mini | CSF | May fix the wrong layer or add deduplication instead of break |
| 5-mini | CSF | Nested retry with distractor is near the capability boundary |

---

<a id="silent-default-a"></a>

# Case: silent_default_a

**Family:** silent_default
**Difficulty:** A (Easy)
**Bug Pattern:** silent_failure
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F5: Information bias (measurement silently corrupted by wrong key)

---

## Task Prompt

> Refactor this feature flag module for clarity. Return the updated code.

## What the Code Does

A single-file feature flag system in `flags.py`:

```python
FLAGS = {
    "dark_mode": True,
    "beta_features": False,
    "new_dashboard": True,
    "analytics_v2": False,
}

def is_enabled(flag_name):
    # BUG: callers pass camelCase ("darkMode") but dict uses snake_case ("dark_mode")
    return FLAGS.get(flag_name, False)
```

`is_enabled(flag_name)` looks up the flag with `.get(flag_name, False)`. `list_flags()` returns all flag names.

## The Bug

The `FLAGS` dictionary uses snake_case keys (`"dark_mode"`, `"beta_features"`, etc.), but callers pass camelCase (`"darkMode"`). The `.get()` call silently returns the default `False` for any camelCase key because it does not match any snake_case key in the dictionary. Features that are enabled appear disabled.

**Violated invariant:** Flag lookup must return the configured value, not silent default.

## The Correct Fix

Add a key normalization function that converts camelCase to snake_case in `flags.py`:

```python
def _normalize_key(flag_name):
    import re
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", flag_name)
    return s1.lower()

def is_enabled(flag_name):
    key = _normalize_key(flag_name)  # FIX: normalize key to snake_case
    return FLAGS.get(key, False)
```

**Lines changed:** 1 (in `is_enabled`, plus the helper function)

## What the Test Checks

1. `is_enabled("darkMode")` returns `True` -- camelCase correctly resolves to snake_case key `"dark_mode"` which is `True`

## Why This Is Difficult for LLMs

- **Refactor framing hides the bug:** The task says "refactor for clarity," not "fix a bug." A model focused on code structure may not realize the key format mismatch.
- **Silent failure with plausible default:** `.get(key, False)` returns `False` for missing keys, which is a plausible value for a feature flag. There is no error, no exception -- the flag simply appears disabled.
- **Convention mismatch is subtle:** The difference between `"darkMode"` (camelCase) and `"dark_mode"` (snake_case) is a naming convention issue, not a structural bug. The model must recognize that callers use a different convention than the dictionary.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible by examining the dictionary keys (snake_case) and the caller convention (camelCase mentioned in the BUG comment). The mismatch is a direct association between key format and lookup format, requiring no cross-function tracing.

### Trap Type: F5: Information bias (measurement silently corrupted by wrong key)

The `.get()` call is a "measurement" of the flag's value. When the key format is wrong, the measurement is silently corrupted -- it returns the default `False` instead of the actual configured value. This is information bias: the measurement instrument (key lookup) systematically misreports the true value due to a calibration error (wrong key format).

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-file or cross-function reasoning is needed. The bug, dictionary, and lookup are all in the same file.
- **Not L3:** No counterfactual or multi-step reasoning is required.

## Failure Mode Being Tested

**silent_failure** with secondary **distributed_configuration** -- A key format mismatch causes dictionary lookups to silently return the default value instead of the configured value. The silence of `.get()` with a default makes this a classic silent-failure pattern.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to refactor structure without recognizing the key format mismatch |
| 4o-mini | Heuristic | May notice the camelCase/snake_case issue but might not add normalization |
| 5-mini | CSF | Should identify the convention mismatch and add key normalization |

---

<a id="silent-default-b"></a>

# Case: silent_default_b

**Family:** silent_default
**Difficulty:** B (Medium)
**Bug Pattern:** silent_failure
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F5: Information bias (measurement silently corrupted by wrong key)

---

## Task Prompt

> Analytics flag always off despite being enabled in config. Fix. Return the updated code.

## What the Code Does

Two files implement a nested configuration with feature flags:

**`config.py`** stores a nested dictionary:

```python
_CONFIG = {
    "feature": {
        "dark_mode": True,
        "beta": False,
        "analytics": {"enabled": True, "version": 2},
    },
    "ui": {"theme": "light", "sidebar": True},
}
```

It also provides `validate_config()` which only checks top-level keys ("feature", "ui").

**`flags.py`** provides dot-path traversal:

```python
def get_flag(path, default=False):
    keys = path.split(".")
    current = _CONFIG
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current

def is_analytics_enabled():
    # BUG: uses "features" (plural) instead of "feature" (singular)
    return get_flag("features.analytics.enabled")
```

## The Bug

`is_analytics_enabled()` passes the path `"features.analytics.enabled"` to `get_flag()`. The first key `"features"` does not exist in `_CONFIG` (the correct key is `"feature"` -- singular). The `get_flag` traversal fails at the first step and silently returns the default `False`, even though `_CONFIG["feature"]["analytics"]["enabled"]` is `True`.

**Violated invariant:** Flag lookup must return the configured value, not silent default.

## The Correct Fix

Change `"features"` to `"feature"` in `is_analytics_enabled()` in `flags.py` (line 31):

```python
return get_flag("feature.analytics.enabled")  # FIX: "feature" not "features"
```

**Lines changed:** 1

## What the Test Checks

1. `is_analytics_enabled()` returns `True` -- the analytics flag is enabled in the config

## Why This Is Difficult for LLMs

- **Trap: `validate_config` checks top-level only.** The `config.py` module has a `validate_config()` function that verifies the top-level keys exist, which might give the model false confidence that the config is correctly accessed.
- **Cross-file reasoning:** The model must compare the path string in `flags.py` against the actual dictionary structure in `config.py` to spot the singular/plural mismatch.
- **Single character difference:** `"features"` vs `"feature"` -- the plural "s" is the entire bug. This is easy to miss during text comparison.
- **Silent fallback:** The `get_flag` function gracefully returns `False` for any missing path. No error is raised, making the failure invisible at runtime.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens when `is_analytics_enabled()` calls `get_flag('features.analytics.enabled')`?" This requires:
1. Splitting the path into `["features", "analytics", "enabled"]`
2. Looking up `"features"` in `_CONFIG` (from config.py) -- not found
3. Recognizing the fallback to `False`
4. Comparing with the correct key `"feature"` to identify the typo

This crosses the boundary between `flags.py` and `config.py`.

### Trap Type: F5: Information bias (measurement silently corrupted by wrong key)

The dot-path traversal is a measurement of the config value. The wrong intermediate key (`"features"` instead of `"feature"`) silently corrupts the measurement, returning the default instead of the actual value. The measurement instrument (path traversal) has a calibration error (typo in the path) that systematically misreports the value.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug requires cross-file comparison between the path string in `flags.py` and the dictionary structure in `config.py`.
- **Not L3:** No multi-step counterfactual chain is needed. A single traversal trace reveals the mismatch at the first key.

## Failure Mode Being Tested

**silent_failure** with secondary **distributed_configuration** -- A key typo in a dot-path traversal causes silent fallback to a default value. The config structure and the access code are in different files, requiring cross-file string comparison to detect the mismatch.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the dot-path traversal across files to spot the singular/plural typo |
| 4o-mini | REI | May focus on validate_config (which passes) rather than the path string |
| 5-mini | CSF | Should trace the path traversal and catch the "features" vs "feature" mismatch |

---

<a id="silent-default-c"></a>

# Case: silent_default_c

**Family:** silent_default
**Difficulty:** C (Hard)
**Bug Pattern:** silent_failure
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F5: Information bias (measurement silently corrupted by wrong key)

---

## Task Prompt

> Feature flag ignores env var override. Fix. Return the updated code.

## What the Code Does

Three files implement a feature flag system with a fallback chain:

**`env.py`** simulates environment variables:

```python
_ENV = {
    "FEATURE_DARK_MODE": "true",
    "FEATURE_BETA": "false",
    "FEATURE_ANALYTICS": "true",
    "APP_DEBUG": "false",
}
```

Provides `get_env(key)` and `get_env_bool(key)` which recognizes "true"/"1"/"yes" as True.

**`config.py`** provides a file-based config store:

```python
_FILE_CONFIG = {
    "dark_mode": True,
    "beta": False,
    "analytics": True,
}
```

Provides `get_config(key)` and `get_config_bool(key)`.

**`flags.py`** implements the fallback chain (env -> config -> hardcoded):

```python
_ENV_KEY_MAP = {
    "dark_mode": "FEATURE_DARKMODE",       # BUG: should be "FEATURE_DARK_MODE"
    "beta": "FEATURE_BETA",
    "analytics": "FEATURE_ANALYTICS",
}

def is_enabled(flag_name):
    env_key = _ENV_KEY_MAP.get(flag_name)
    if env_key:
        env_val = get_env_bool(env_key)
        if env_val:
            return True
    config_val = get_config_bool(flag_name)
    if config_val is not None:
        return config_val
    return HARDCODED_DEFAULTS.get(flag_name, False)
```

## The Bug

`_ENV_KEY_MAP` maps `"dark_mode"` to `"FEATURE_DARKMODE"` (missing underscore between DARK and MODE), but the actual environment variable is `"FEATURE_DARK_MODE"`. When `is_enabled("dark_mode")` checks the env layer, `get_env_bool("FEATURE_DARKMODE")` looks up a key that does not exist in `_ENV`, silently returns `False`, and the fallback chain skips the env layer entirely. The flag falls through to the config layer instead.

In this specific case, `config.py` also has `dark_mode: True`, so `is_enabled("dark_mode")` still returns `True` -- but from the wrong source. The `get_flag_source("dark_mode")` function returns `"config"` instead of `"env"`, revealing that the env override is being silently ignored.

**Violated invariant:** Flag lookup must return the configured value, not silent default.

## The Correct Fix

Fix the env key mapping in `_ENV_KEY_MAP` in `flags.py` (line 21):

```python
"dark_mode": "FEATURE_DARK_MODE",      # FIX: correct underscore in env key
```

**Lines changed:** 1

## What the Test Checks

1. `get_flag_source("dark_mode")` returns `"env"` -- the env layer should be the source, not config or hardcoded

## Why This Is Difficult for LLMs

- **Trap: Fallback chain looks resilient.** The 3-layer fallback (env -> config -> hardcoded) is designed for resilience. A model may see this design pattern and assume it works correctly, without tracing each layer's key lookup.
- **Bug is masked by correct final result.** `is_enabled("dark_mode")` returns `True` regardless -- the env and config layers agree. The bug only shows when checking the *source* of the value, not the value itself.
- **Three-file key tracing:** The model must trace the key through: `flags.py` (map "dark_mode" -> "FEATURE_DARKMODE") -> `env.py` (lookup "FEATURE_DARKMODE" in _ENV -- not found) -> fallback to `config.py`. This is a 3-file chain.
- **Subtle string difference:** `"FEATURE_DARKMODE"` vs `"FEATURE_DARK_MODE"` -- a single missing underscore. The strings look almost identical.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform deterministic state tracing across modules through the fallback chain:
1. Tracing `is_enabled("dark_mode")` through the env layer lookup in `flags.py` -- forward path analysis
2. Following the mapped key `"FEATURE_DARKMODE"` into `env.py`'s `_ENV` dictionary -- mechanism verification
3. Recognizing the key mismatch (missing underscore) -- deterministic string comparison
4. Understanding that the fallback chain silently skips the env layer -- multi-step causal propagation
5. Tracing the fallback to the config layer and verifying the source attribution

This is multi-step causal propagation across three files with mechanism verification at the key-mapping boundary, where the bug is masked by a correct final result from a lower-priority source.

### Trap Type: F5: Information bias (measurement silently corrupted by wrong key)

The `_ENV_KEY_MAP` is an index that maps flag names to environment variable names. The wrong key (`"FEATURE_DARKMODE"` instead of `"FEATURE_DARK_MODE"`) corrupts the env lookup, causing the measurement (env check) to silently report "not found" when the variable actually exists. The information bias propagates through the fallback chain, which silently compensates by using a lower-priority source.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug spans three files and requires comparing string constants across module boundaries.
- **L2 (deep):** The model must trace the fallback chain across three files, verify the mechanism at the key-mapping step (comparing `"FEATURE_DARKMODE"` against `"FEATURE_DARK_MODE"` in `_ENV`), and propagate the causal effect of the typo through the fallback to identify that the wrong source is used. This is multi-step causal propagation with mechanism verification at each layer of the fallback chain.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The key mapping, the dictionary lookup failure, and the fallback to config are all directly observable from tracing the actual execution forward.

## Failure Mode Being Tested

**silent_failure** with secondary **distributed_configuration** -- A key typo in an environment variable mapping causes the env layer to be silently bypassed. The fallback chain compensates by using a lower-priority source, masking the bug in the final result but revealing it in the source attribution.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the 3-layer fallback chain or spot the underscore difference |
| 4o-mini | CSF | May see the fallback chain as correct and not trace individual key lookups |
| 5-mini | CSF | Best chance, but the masked bug (correct result, wrong source) is very subtle |

---

<a id="stale-cache-a"></a>

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

---

<a id="stale-cache-b"></a>

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

---

<a id="stale-cache-c"></a>

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

---

<a id="temporal-drift-a"></a>

# Case: temporal_drift_a

**Family:** temporal_drift
**Difficulty:** A (Easy)
**Bug Pattern:** implicit_schema
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F4: Reverse causation / Direction error

---

## Task Prompt

> Refactor this metrics pipeline for clarity. Return the updated code.

## What the Code Does

A single-file metrics pipeline (`pipeline.py`) that computes raw statistics on input data and then normalizes the data.

```python
def compute_raw_stats(data):
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0}
    return {
        "raw_max": max(data),
        "raw_min": min(data),
        "raw_sum": sum(data),
    }

def normalize(data):
    if not data:
        return []
    lo, hi = min(data), max(data)
    if hi == lo:
        return [0.5] * len(data)
    return [(x - lo) / (hi - lo) for x in data]

def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)  # BUG: should be data, not cleaned
    return {"raw_stats": raw_stats, "cleaned": cleaned}
```

The contract: `raw_stats` must reflect the ORIGINAL input data, not the normalized version. The function name `compute_raw_stats` implies it operates on raw data.

## The Bug

`compute_raw_stats()` is called on `cleaned` (the normalized data, range 0-1) instead of `data` (the original input). After normalization, `raw_max` is always 1.0, `raw_min` is always 0.0, and `raw_sum` is the sum of normalized values -- none of which reflect the original data.

The ordering is backwards: normalize runs first, then raw stats are computed on the already-transformed data. This is a temporal ordering error -- the computation that must run on raw data was placed after the transformation.

## The Correct Fix

Swap the argument from `cleaned` to `data`:

```python
def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(data)  # fixed: use original data
    return {"raw_stats": raw_stats, "cleaned": cleaned}
```

Or equivalently, move `compute_raw_stats` before `normalize`:

```python
def pipeline(data):
    raw_stats = compute_raw_stats(data)
    cleaned = normalize(data)
    return {"raw_stats": raw_stats, "cleaned": cleaned}
```

**Lines changed:** 1 (change `cleaned` to `data` in the `compute_raw_stats` call)

## What the Test Checks

1. Call `pipeline([10, 50, 30, 80, 20])`
2. **Assert:** `raw_stats["raw_max"] == 80` (not 1.0 from normalized data)
3. **Assert:** `raw_stats["raw_min"] == 10` (not 0.0 from normalized data)
4. **Assert:** `raw_stats["raw_sum"] == 190` (not ~2.57 from normalized data)

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model may reorganize the pipeline without noticing the argument error.
- **The code runs without errors.** `compute_raw_stats(cleaned)` produces valid output -- just with wrong values (0.0 to 1.0 range instead of original values).
- **Direction error (F4):** The causal direction is reversed. The code implies "normalize data, then compute stats on the result." But the correct direction is "compute stats on raw data, then normalize." The function name `compute_raw_stats` hints at the correct argument, but the actual call uses the wrong variable.
- **`format_report()` distractor:** A helper function that formats the stats for display. It is unrelated to the bug but may draw attention.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible in one function (`pipeline`). The variable name `cleaned` (post-normalization) vs. `data` (original), combined with the function name `compute_raw_stats`, creates a pattern mismatch that can be detected through local association.

### Trap Type: F4: Reverse causation / Direction error

The temporal/causal direction is wrong. Raw stats should be computed BEFORE transformation, but the code computes them AFTER. This is a direction error: the model must recognize that the arrow goes from raw data -> stats, not from transformed data -> stats.

### Why This Case Is L1, Not L2 or L3

**Not L2** because `compute_raw_stats` and `normalize` are both defined in the same file. The pipeline function that contains the bug is self-contained -- no cross-file reasoning needed.

**Not L3** because there is a single transformation step and a single stats computation. No multi-step state evolution or multiple interacting pipelines.

## Failure Mode Being Tested

**TEMPORAL_DRIFT** (implicit_schema) -- a computation that must run on raw data is placed after a transformation, causing it to operate on the wrong version of the data. The implicit schema (raw_stats contract) is violated silently.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May recognize the naming mismatch but fail to change the argument |
| 4o-mini | Heuristic | Likely to notice raw_stats should use raw data |
| 5-mini | CSF | Should identify the argument error from naming alone |

---

<a id="temporal-drift-b"></a>

# Case: temporal_drift_b

**Family:** temporal_drift
**Difficulty:** B (Medium)
**Bug Pattern:** implicit_schema
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F4: Reverse causation / Direction error

---

## Task Prompt

> Raw stats show normalized values instead of actual. Fix. Return the updated code.

## What the Code Does

A two-file metrics pipeline. `transforms.py` provides three functions: `compute_raw_stats()`, `normalize()`, and `summarize_for_display()`. `pipeline.py` orchestrates the flow.

**transforms.py:**
```python
def compute_raw_stats(data):
    """Must be called on original data before any transforms."""
    if not data:
        return {"raw_max": 0, "raw_min": 0, "raw_sum": 0}
    return {"raw_max": max(data), "raw_min": min(data), "raw_sum": sum(data)}

def normalize(data):
    """Normalize data to 0-1 range."""
    ...

def summarize_for_display(cleaned):
    """Returns display_max, display_min, display_mean -- NOT raw keys.
    Distractor: similar to compute_raw_stats but different contract."""
    ...
```

**pipeline.py:**
```python
def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(cleaned)  # BUG: should be data, not cleaned
    display = summarize_for_display(cleaned)
    return {"raw_stats": raw_stats, "cleaned": cleaned, "display": display}
```

The contract: `raw_stats` must reflect original data. `summarize_for_display` returns different keys (`display_max`, etc.) and correctly operates on cleaned data.

## The Bug

Same core bug as temporal_drift_a: `compute_raw_stats()` is called on `cleaned` (normalized, 0-1 range) instead of `data` (original values). But now the function is defined in a different file (`transforms.py`), and a distractor function `summarize_for_display()` has a similar signature but different keys and a correct contract (it should operate on cleaned data).

The direction error means raw_stats returns normalized values (max=1.0, min=0.0) instead of actual values.

## The Correct Fix

Change the argument from `cleaned` to `data`:

```python
def pipeline(data):
    cleaned = normalize(data)
    raw_stats = compute_raw_stats(data)  # fixed: use original data
    display = summarize_for_display(cleaned)
    return {"raw_stats": raw_stats, "cleaned": cleaned, "display": display}
```

**Lines changed:** 1 (change `cleaned` to `data` in the `compute_raw_stats` call)

## What the Test Checks

1. Call `pipeline([100, 200, 300, 400, 500])`
2. **Assert:** `raw_stats["raw_max"] == 500` (not 1.0)
3. **Assert:** `raw_stats["raw_min"] == 100` (not 0.0)
4. **Assert:** `raw_stats["raw_sum"] == 1500` (not ~2.5)

## Why This Is Difficult for LLMs

- **Distractor: `summarize_for_display()`** looks similar to `compute_raw_stats()` -- both take a data array and return summary statistics. But they have different contracts and different key names. A model might consolidate them or swap their arguments, breaking the pipeline.
- **Cross-file separation:** The docstring of `compute_raw_stats` in `transforms.py` says "Must be called on original data before any transforms," but the call site in `pipeline.py` uses `cleaned`. The model must read the docstring across the file boundary.
- **`quick_summary()` distractor:** A function in `pipeline.py` that only uses `summarize_for_display`, suggesting the display path is the important one. This may divert attention from the `raw_stats` bug.
- **Direction error (F4):** The code flows linearly: normalize -> raw_stats -> display. The temporal ordering looks natural (process, then summarize). The model must recognize that `raw_stats` should break this linear flow by operating on pre-transform data.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason: "If I change the argument of `compute_raw_stats` from `cleaned` to `data`, the returned stats will reflect original values instead of normalized values." This requires understanding the intervention's effect across the file boundary (the function is in `transforms.py`, the call is in `pipeline.py`).

### Trap Type: F4: Reverse causation / Direction error

The causal direction is reversed: raw stats should precede transformation in the data flow, but the code computes them after. The `summarize_for_display` distractor reinforces the wrong direction -- it correctly operates on cleaned data, making the pattern "compute stats on cleaned" look intentional.

### Why This Case Is L2, Not L1 or L3

**Not L1** because `compute_raw_stats` is defined in `transforms.py` and called from `pipeline.py`. The model must read the cross-file docstring to understand the contract.

**Not L3** because there is still only one transformation step and one stats computation, just split across two files. The distractor adds complexity but not additional state evolution steps.

## Failure Mode Being Tested

**TEMPORAL_DRIFT** (implicit_schema) -- a computation with an implicit contract (must operate on raw data) is called on post-transform data. The cross-file distractor makes the direction error harder to detect.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the cross-file contract with distractor |
| 4o-mini | REI | May identify the issue but confuse raw_stats with summarize_for_display |
| 5-mini | CSF | Should trace the contract across files and fix the argument |

---

<a id="temporal-drift-c"></a>

# Case: temporal_drift_c

**Family:** temporal_drift
**Difficulty:** C (Hard)
**Bug Pattern:** implicit_schema
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F4: Reverse causation / Direction error

---

## Task Prompt

> Report shows wrong raw metrics. Fix the pipeline. Return the updated code.

## What the Code Does

A three-file, four-stage metrics pipeline.

**transforms.py** provides:
- `normalize(data)` -- normalize to 0-1 range
- `clip(data, lower, upper)` -- clip values to a range
- `scale(data, factor)` -- scale values by a factor
- `summarize_for_display(cleaned)` -- returns `display_max`, `display_min`, `display_mean` (NOT raw keys)

**metrics.py** provides:
- `compute_raw_stats(data)` -- returns `raw_max`, `raw_min`, `raw_sum`, `raw_count` (must be called on original data)
- `compute_derived(raw_stats)` -- computes `raw_mean` from raw stats

**pipeline.py** orchestrates the four stages:
```python
def pipeline(data):
    # Stage 2: normalize
    normalized = normalize(data)
    # Stage 3: clip
    clipped = clip(normalized, 0.05, 0.95)
    # Stage 1: raw stats -- MISPLACED
    raw_stats = compute_raw_stats(normalized)  # BUG: should be data, not normalized
    derived = compute_derived(raw_stats)
    # Stage 4: display summary
    display = summarize_for_display(clipped)
    return {
        "raw_stats": raw_stats, "derived": derived,
        "cleaned": clipped, "display": display,
    }
```

The stages are numbered in comments but executed out of order. Stage 1 (raw stats) is computed AFTER stages 2 and 3, and uses `normalized` instead of `data`.

## The Bug

`compute_raw_stats()` is called on `normalized` (post-normalization, 0-1 range) instead of `data` (original values). The stage ordering in the code contradicts the numbered comments: "Stage 1: raw stats" runs third. The raw stats contain normalized values: `raw_max` is 1.0 instead of the actual maximum.

Additionally, `compute_derived()` propagates the error -- `raw_mean` is computed from the wrong raw stats, creating a second-order effect.

## The Correct Fix

Change the argument from `normalized` to `data`:

```python
def pipeline(data):
    normalized = normalize(data)
    clipped = clip(normalized, 0.05, 0.95)
    raw_stats = compute_raw_stats(data)  # fixed: use original data
    derived = compute_derived(raw_stats)
    display = summarize_for_display(clipped)
    return {
        "raw_stats": raw_stats, "derived": derived,
        "cleaned": clipped, "display": display,
    }
```

**Lines changed:** 1 (change `normalized` to `data` in the `compute_raw_stats` call)

## What the Test Checks

1. Call `pipeline([15, 45, 90, 120, 60])`
2. **Assert:** `raw_stats["raw_max"] == 120` (not 1.0 from normalized)
3. **Assert:** `raw_stats["raw_min"] == 15` (not 0.0 from normalized)
4. **Assert:** `raw_stats["raw_sum"] == 330` (not ~2.57 from normalized)
5. **Assert:** `raw_stats["raw_count"] == 5`

## Why This Is Difficult for LLMs

- **Four stages with misordered comments:** The stage numbering (1-4) in comments does not match execution order. "Stage 1: raw stats" runs after stages 2 and 3. Models may trust the comments and not notice the execution order mismatch.
- **Three files to trace:** The model must understand `transforms.py` (normalize, clip, summarize_for_display), `metrics.py` (compute_raw_stats, compute_derived), and `pipeline.py` (orchestration).
- **Trap: consolidating `compute_raw_stats` and `summarize_for_display`.** They have similar signatures but different key names (`raw_*` vs `display_*`). Merging them breaks the API. The docstring in `transforms.py` explicitly warns about this.
- **`quick_report()` distractor:** A function in `pipeline.py` that uses only `normalize` and `summarize_for_display`, suggesting the display path is the "normal" one. This diverts attention from the raw stats bug.
- **Second-order error:** `compute_derived(raw_stats)` computes `raw_mean` from the wrong raw stats. Even if the model fixes `compute_raw_stats`, it might not realize `compute_derived` is automatically fixed too (it is, since it reads from `raw_stats`).
- **Direction error (F4) in a multi-stage pipeline:** With two transformation steps (normalize, clip) before the raw stats computation, the direction error is compounded. The model must recognize that raw stats should be computed before ANY transformation, not just before the last one.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through a four-stage pipeline: trace the data flow to see that `normalize(data)` transforms the original values, then `compute_raw_stats(normalized)` receives already-transformed data instead of the original `data`. This is deterministic state tracing across modules -- the model verifies the mechanism by checking what each function receives and returns, identifying that `compute_raw_stats` is called on the wrong variable. The second-order effect through `compute_derived` is also deterministic forward propagation.

### Trap Type: F4: Reverse causation / Direction error

The direction error is embedded in a multi-stage pipeline. Two transformations (normalize, clip) intervene between the raw data and the raw stats computation. The numbered comments suggest the "correct" stage order but the code executes them differently. The model must reason about which data version each function should receive.

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the pipeline spans three files with four stages. No single-file analysis reveals the full data flow.

**L2 (deep)** because the model must trace data through multiple transformation stages across three files, verify the mechanism at each stage (normalize, clip, raw stats, derived), and identify which variable is passed to `compute_raw_stats`. The misordered stage comments, the distractor (`summarize_for_display`), and the second-order effect (`compute_derived`) add complexity, but all reasoning is multi-step causal propagation through deterministic code paths.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The variable names, function arguments, and transformation results are all directly observable from tracing the pipeline forward.

## Failure Mode Being Tested

**TEMPORAL_DRIFT** (implicit_schema) -- a computation with an implicit "must-run-on-raw-data" contract is placed after multiple transformations in a multi-stage pipeline. The three-file architecture, misordered stage comments, and consolidation trap make this the hardest case in the family.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace 4-stage pipeline across 3 files |
| 4o-mini | CSF | May identify the issue but confuse the multiple transformation stages |
| 5-mini | CSF | Multi-stage pipeline with distractors is near the capability boundary |

---

<a id="use-before-set-a"></a>

# Case: use_before_set_a

**Family:** use_before_set
**Difficulty:** A (Easy)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F5: Information bias (empty/edge input is invisible path)

---

## Task Prompt

> Refactor this data transform for clarity. Return the updated code.

## What the Code Does

A single-file data transformation module (`transform.py`) with a `transform()` function that doubles each element in the input list and caches the result in `_last_result`.

```python
_last_result = []

def transform(data):
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    # BUG: when data is empty/falsy, returns stale _last_result
    return _last_result
```

When `data` is non-empty, a fresh `result` list is built and cached. When `data` is empty or falsy, the `if` branch is skipped entirely, and the function returns whatever `_last_result` held from a previous call.

## The Bug

When `data` is empty (`[]`), the function skips the `if data:` block and returns `_last_result`, which contains the result from the previous call. This is a classic "use before set on a conditional path" bug: the variable `_last_result` is only updated when input is non-empty, but is always returned.

The bug is silent -- no exception, no wrong type -- the function returns a valid list. But it returns **stale data**, violating the contract that each call should return a fresh result for its input.

## The Correct Fix

Initialize `_last_result` to an empty list when `data` is falsy:

```python
def transform(data):
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    else:
        _last_result = []
    return _last_result
```

**Lines changed:** 1-2 (add `else: _last_result = []` branch)

## What the Test Checks

1. Call `transform([1, 2, 3])` -- populate stale state
2. Call `transform([])` -- empty input
3. **Assert:** `transform([]) == []` -- must return empty list, not stale `[2, 4, 6]`

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model may reorganize the code without noticing the empty-input path is broken.
- **Information bias (F5):** Training data overwhelmingly shows non-empty inputs. The empty-input code path is rarely exercised in examples, making it invisible to pattern-matching approaches.
- **The code looks correct for non-empty input.** A model testing only the happy path would see correct behavior and conclude the code is fine.
- **Common wrong fix:** Removing the caching entirely (changes the API contract) or adding a check for `None` but not for `[]`.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible within a single function body. Reading the `if data:` guard and the unconditional `return _last_result` reveals the problem through local pattern matching: the conditional sets `_last_result` only when data is truthy, but the return always uses it.

### Trap Type: F5: Information bias (empty/edge input is invisible path)

The F5 trap works because empty inputs are underrepresented in training data. Models associate `transform(data)` with the common case where `data` contains elements. The edge case where `data` is `[]` is an invisible path -- the model never "sees" it unless it explicitly traces the conditional branch.

### Why This Case Is L1, Not L2 or L3

**Not L2** because the entire bug -- the conditional guard, the missing else-branch, and the stale return -- is in one function in one file. No cross-function reasoning is needed.

**Not L3** because there is no multi-step state evolution. The stale-state behavior is a single-step consequence of skipping the `if` block.

## Failure Mode Being Tested

**USE_BEFORE_SET** (edge_case_omission) -- a variable is conditionally set but unconditionally read. The empty-input edge case exposes stale state from a previous invocation.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May describe the empty-input issue but fail to produce the else-branch |
| 4o-mini | Heuristic | Likely to handle refactoring but may miss the stale-state edge case |
| 5-mini | CSF | Should identify the missing else-branch on empty input |

---

<a id="use-before-set-b"></a>

# Case: use_before_set_b

**Family:** use_before_set
**Difficulty:** B (Medium)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F5: Information bias (empty/edge input is invisible path)

---

## Task Prompt

> Pipeline crashes on empty data source. Fix. Return the updated code.

## What the Code Does

A two-file pipeline system. `loader.py` loads data from a source and tracks status. `pipeline.py` calls the loader and returns a status-tagged result.

**loader.py:**
```python
_status = "idle"
_data = None

def load(source):
    global _status, _data
    if source and len(source) > 0:
        _data = [x for x in source]
        _status = "loaded"
    # BUG: on empty/None source, _status stays at previous value
    return _data
```

**pipeline.py:**
```python
def run_pipeline(source):
    load(source)
    status = get_status()
    data = get_data()
    return {
        "status": status,
        "count": len(data) if data else 0,
        "data": data,
    }
```

The contract: `status` in the returned dict must reflect THIS call's outcome. After loading empty data, status should not be "loaded."

## The Bug

In `loader.py`, `_status` is only set to `"loaded"` inside the `if source and len(source) > 0:` block. When the source is empty, `_status` retains whatever value it had from a previous call. If a previous call loaded data successfully, `_status` is still `"loaded"` even though the current call loaded nothing.

`pipeline.py` reads `get_status()` unconditionally and trusts whatever the loader reports. There is no independent check -- the pipeline inherits the stale status.

## The Correct Fix

Set `_status` to `"empty"` (or `"idle"`) when source is empty:

```python
def load(source):
    global _status, _data
    if source and len(source) > 0:
        _data = [x for x in source]
        _status = "loaded"
    else:
        _data = None
        _status = "empty"
    return _data
```

**Lines changed:** 1-3 (add else-branch that resets `_status` and `_data`)

## What the Test Checks

1. Reset module state (`_status = "idle"`, `_data = None`)
2. Call `run_pipeline([10, 20, 30])` -- first call loads data, sets status to "loaded"
3. Call `run_pipeline([])` -- second call with empty data
4. **Assert:** `r2["status"] != "loaded"` -- status must not leak from previous call
5. **Assert:** `r2["count"] == 0` -- count must reflect empty input

## Why This Is Difficult for LLMs

- **Cross-file stale state:** The bug is in `loader.py` but manifests through `pipeline.py`. The model must trace the `get_status()` call across the file boundary to understand that the loader's stale `_status` propagates.
- **The loader looks like it "handles" empty input:** It returns `_data` (which is `None` initially), so the return value is technically correct for empty input. The status leakage is a secondary, silent failure.
- **Distractor function:** `validate_format()` in `loader.py` checks data format and returns `False` for `None`, looking like a potential fix point. But the bug is in `load()`, not in validation.
- **Information bias (F5):** Models trained on typical load/process patterns rarely see empty-source scenarios. The "load succeeds" path dominates training data.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about an intervention: "If I add an else-branch in `load()` that resets `_status`, then `get_status()` in `pipeline.py` would return the correct value." This requires understanding the causal chain from loader state to pipeline output across the file boundary.

### Trap Type: F5: Information bias (empty/edge input is invisible path)

The empty-source path is invisible in typical usage. Models associate `load(source)` with success. The fact that `_status` persists across calls is a hidden dependency that only manifests when the invisible (empty) path is exercised after a successful call.

### Why This Case Is L2, Not L1 or L3

**Not L1** because the bug is in `loader.py` but the invariant ("status must reflect this call") is enforced in `pipeline.py`. Understanding the failure requires tracing the `get_status()` call across one file boundary.

**Not L3** because there is only one cross-file dependency to trace (loader -> pipeline). No multi-step state evolution or multiple interacting modules are involved.

## Failure Mode Being Tested

**USE_BEFORE_SET** (edge_case_omission) -- module-level state is set only on the success path. When the edge case (empty input) occurs, stale state from a previous call leaks through to consumers.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace stale state across file boundary |
| 4o-mini | REI | May identify the status issue but fix it in pipeline instead of loader |
| 5-mini | CSF | Should trace the cross-file dependency and fix the loader |

---

<a id="use-before-set-c"></a>

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

---

<a id="wrong-condition-a"></a>

# Case: wrong_condition_a

**Family:** wrong_condition
**Difficulty:** A (Easy)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F2: Statistical artifact (boundary value treated incorrectly)

---

## Task Prompt

> Refactor this rate limiter for clarity. Return the updated code.

## What the Code Does

A single-file rate limiter in `limiter.py` with two functions:

```python
def is_rate_limited(count, limit):
    # BUG: uses > instead of >=
    return count > limit

def check_and_increment(current_count, limit):
    if is_rate_limited(current_count, limit):
        return True, current_count
    return False, current_count + 1
```

`is_rate_limited(count, limit)` should return True when the count has reached the limit, blocking further requests. `check_and_increment` uses it as a gate before incrementing.

## The Bug

The comparison uses `>` instead of `>=`. When `count == limit`, the function returns `False` (not rate-limited), allowing one extra request beyond the limit. For example, with `limit=5`, a count of 5 means 5 requests have already been made and should be blocked, but `5 > 5` is `False`, so the 6th request is allowed.

**Violated invariant:** Boundary condition must be handled correctly.

## The Correct Fix

Change `>` to `>=` on line 17 of `limiter.py`:

```python
return count >= limit  # FIX: uses >= so count==limit is blocked
```

**Lines changed:** 1

## What the Test Checks

1. `is_rate_limited(5, 5)` returns `True` (at the limit, should block)

## Why This Is Difficult for LLMs

- **Refactor framing:** The task says "refactor for clarity," not "fix a bug." A model focused on naming, structure, or docstrings may preserve the `>` operator.
- **Off-by-one subtlety:** The difference between `>` and `>=` is a single character. The code works correctly for all values except the exact boundary (`count == limit`).
- **Both operators "make sense":** A model reasoning about the natural language ("has the count exceeded the limit?") might keep `>` because "exceeded" can mean "gone past." The correct reading is "reached," not "exceeded."

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is identifiable by direct inspection of the comparison operator against the function's documented semantics. No cross-function tracing or intervention simulation is needed -- just recognizing that `>` allows the boundary case when `>=` is required.

### Trap Type: F2: Statistical artifact (boundary value treated incorrectly)

The `>` vs `>=` distinction is a statistical-artifact-style error: for nearly all inputs, both operators produce the same result. The bug only manifests at the exact boundary value (`count == limit`), creating an artifact where the system appears correct on aggregate testing but fails at the critical threshold.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-function or cross-file reasoning is needed. The bug is in a single comparison on a single line.
- **Not L3:** No counterfactual multi-step chain is involved. The fix is a direct operator change.

## Failure Mode Being Tested

**edge_case_omission** -- An off-by-one error in a comparison operator silently allows one extra request at the boundary. The bug is invisible for all non-boundary inputs, making it a classic edge-case omission.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to refactor naming/structure without examining operator semantics |
| 4o-mini | Heuristic | May recognize off-by-one pattern but could rationalize keeping > |
| 5-mini | CSF | Should identify the boundary condition error through operator analysis |

---

<a id="wrong-condition-b"></a>

# Case: wrong_condition_b

**Family:** wrong_condition
**Difficulty:** B (Medium)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F3: Simpson's paradox variant (each sub-check correct, composition wrong)

---

## Task Prompt

> Rate limiter allows too many requests. Fix the policy. Return the updated code.

## What the Code Does

Two files implement a rate + quota limiting system:

**`policy.py`** defines individual policy checks:

```python
def check_rate(requests_per_minute, rate_limit):
    return requests_per_minute < rate_limit

def check_quota(daily_total, daily_quota):
    return daily_total < daily_quota

def is_allowed(requests_per_minute, rate_limit, daily_total, daily_quota):
    rate_ok = check_rate(requests_per_minute, rate_limit)
    quota_ok = check_quota(daily_total, daily_quota)
    # BUG: uses 'or' instead of 'and'
    return rate_ok or quota_ok
```

**`limiter.py`** contains a `RateLimiter` class that calls `is_allowed()` to decide whether to permit requests, tracking per-minute and daily counts.

## The Bug

`is_allowed()` in `policy.py` (line 22) uses `or` instead of `and` to combine the rate and quota checks. The docstring says "allowed under BOTH rate and quota policies," but the code allows a request if EITHER condition passes. This means a client can exceed their daily quota as long as their per-minute rate is low, or exceed the per-minute rate as long as they have daily quota left.

**Violated invariant:** Boundary condition must be handled correctly -- both policies must be enforced simultaneously.

## The Correct Fix

Change `or` to `and` on line 22 of `policy.py`:

```python
return rate_ok and quota_ok  # FIX: requires BOTH conditions to pass
```

**Lines changed:** 1

## What the Test Checks

1. `is_allowed(rpm=50, rate_limit=100, daily=10001, quota=10000)` returns `False` (rate OK but quota exceeded -- should block)

## Why This Is Difficult for LLMs

- **Trap: `or` reads naturally in English.** "Is the request allowed if the rate is OK or the quota is OK?" sounds plausible in natural language. The model must override English-language intuition with logical semantics.
- **Cross-file reasoning:** The limiter class in `limiter.py` delegates to `is_allowed()` in `policy.py`. A model examining `limiter.py` alone sees a clean API call and might not dig into the policy logic.
- **Individual checks are correct:** `check_rate` and `check_quota` are each independently correct. The bug is only in how they are composed -- a Simpson's-paradox-like situation where correct sub-components produce incorrect aggregate behavior.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens when I call `is_allowed(50, 100, 10001, 10000)`?" This requires tracing from `limiter.py`'s `try_request()` into `policy.py`'s `is_allowed()`, evaluating each sub-check, and recognizing that `or` produces the wrong composite result. The intervention crosses the file boundary.

### Trap Type: F3: Simpson's paradox variant (each sub-check correct, composition wrong)

Each individual policy check (`check_rate`, `check_quota`) is correct in isolation. The error is in the aggregation operator (`or` vs `and`). This mirrors Simpson's paradox: sub-group behavior is correct, but the aggregate conclusion is reversed due to incorrect composition logic.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug cannot be found by inspecting `limiter.py` alone -- the model must cross into `policy.py` to find the `or` vs `and` error.
- **Not L3:** No multi-step counterfactual chain or temporal reasoning is needed. A single intervention trace (one call through the policy) reveals the bug.

## Failure Mode Being Tested

**edge_case_omission** -- The logical composition of two correct sub-checks uses the wrong operator, silently allowing requests that violate one of the two policies. The bug is masked by the fact that requests violating both policies are still correctly blocked.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not trace into policy.py or may accept 'or' as valid |
| 4o-mini | REI | Likely reads English semantics of 'or' and doesn't question it |
| 5-mini | CSF | Should trace the call and recognize the docstring vs code mismatch |

---

<a id="wrong-condition-c"></a>

# Case: wrong_condition_c

**Family:** wrong_condition
**Difficulty:** C (Hard)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F3: Simpson's paradox variant (precedence makes correct sub-expressions compose incorrectly)

---

## Task Prompt

> Expired tokens still allowed for exempt users. Fix. Return the updated code.

## What the Code Does

Three files implement a rate limiting system with expiration and exemption:

**`policy.py`** provides three predicates: `is_expired(timestamp, now, window_seconds)`, `is_under_limit(count, limit)`, and `is_exempt(client_id, exempt_list)`.

**`limiter.py`** combines the predicates:

```python
def should_allow(client_id, count, limit, timestamp, now,
                 window_seconds, exempt_list):
    expired = is_expired(timestamp, now, window_seconds)
    under_limit = is_under_limit(count, limit)
    exempt = is_exempt(client_id, exempt_list)

    # BUG: operator precedence
    # Python parses as: ((not expired) and under_limit) or exempt
    # Correct intent:   (not expired) and (under_limit or exempt)
    return not expired and under_limit or exempt
```

**`middleware.py`** wires the limiter into request processing, passing client state and default configuration (window=60s, limit=100, exempt_clients={"internal-service", "health-checker"}).

## The Bug

Python's operator precedence evaluates `not expired and under_limit or exempt` as `((not expired) and under_limit) or exempt`. The intended logic is `(not expired) and (under_limit or exempt)`.

When a token is expired (`expired=True`) AND the client is exempt (`exempt=True`):
- **Buggy:** `(False and under_limit) or True` = `True` (allows the request)
- **Correct:** `False and (under_limit or True)` = `False` (blocks the request)

Exempt clients bypass the rate limit, but expired tokens should always be rejected -- even for exempt clients.

**Violated invariant:** Boundary condition must be handled correctly.

## The Correct Fix

Add explicit parentheses on line 26 of `limiter.py`:

```python
return not expired and (under_limit or exempt)  # FIX: explicit parentheses
```

**Lines changed:** 1

## What the Test Checks

1. `should_allow(client_id="internal-service", count=200, limit=100, timestamp=0, now=100, window_seconds=60, exempt_list={"internal-service"})` returns `False` -- expired token must be rejected even for exempt clients

## Why This Is Difficult for LLMs

- **Trap: Boolean reads correctly.** The expression `not expired and under_limit or exempt` reads naturally in English as "not expired and (under the limit or exempt)," which is the correct intent. The Python precedence silently differs from the English reading.
- **Three-file context:** The model must understand the semantics of each predicate from `policy.py`, trace the composition in `limiter.py`, and understand the real-world usage from `middleware.py` to reason about which precedence is correct.
- **Exempt clients are a special case:** The model might reason that exempt clients should always be allowed (since they are "exempt"), missing the constraint that token expiration is an independent, non-bypassable check.
- **Only manifests with specific input combinations:** The bug only appears when `expired=True AND exempt=True`. Most test cases (non-exempt clients, or non-expired exempt clients) pass correctly.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform multi-step causal propagation through the boolean logic:
1. Understanding each predicate's semantics from `policy.py` (mechanism verification)
2. Evaluating Python's operator precedence in `limiter.py` (deterministic state tracing)
3. Reasoning about the design intent from `middleware.py`'s exempt list semantics (forward path analysis)
4. Tracing the specific input combination (expired + exempt) through the precedence rules to see that `((not expired) and under_limit) or exempt` evaluates differently than the intended `(not expired) and (under_limit or exempt)`

This is deterministic state tracing across three files with mechanism verification of Python's operator precedence rules.

### Trap Type: F3: Simpson's paradox variant (precedence makes correct sub-expressions compose incorrectly)

Each individual predicate (`is_expired`, `is_under_limit`, `is_exempt`) is correct. The composition expression uses the right variables and the right logical intent. But Python's operator precedence silently regroups the sub-expressions, creating a paradox where the aggregate behavior contradicts the intended policy -- each sub-check is correct, but the composition is wrong.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug is not visible from inspecting any single file. The expression looks correct to English-language reading.
- **L2 (deep):** The model must trace three predicates across three files, apply Python's operator precedence rules deterministically, and propagate the causal effect of the wrong grouping through specific input values. This is multi-step causal propagation with mechanism verification of language-level precedence rules.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. Python's operator precedence is a fixed rule; the model evaluates the expression step by step, not by comparing two hypothetical worlds.

## Failure Mode Being Tested

**edge_case_omission** -- Operator precedence creates a silent semantic error that only manifests under a specific combination of conditions (expired AND exempt). The natural-language reading of the code matches the intent, but the Python evaluation does not.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot reason about operator precedence across 3 files |
| 4o-mini | CSF | May read the expression as correct English and miss the precedence issue |
| 5-mini | CSF | Best chance but precedence + edge-case input construction is challenging |

---
