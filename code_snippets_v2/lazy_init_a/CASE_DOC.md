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
