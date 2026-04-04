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
