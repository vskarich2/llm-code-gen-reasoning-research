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
