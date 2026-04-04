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
