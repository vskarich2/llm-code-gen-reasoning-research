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
