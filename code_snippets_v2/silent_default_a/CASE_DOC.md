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
