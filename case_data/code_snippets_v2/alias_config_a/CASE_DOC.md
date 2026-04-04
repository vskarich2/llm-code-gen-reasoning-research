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
