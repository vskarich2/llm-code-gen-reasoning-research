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
