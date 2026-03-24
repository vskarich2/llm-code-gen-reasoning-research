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
