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
