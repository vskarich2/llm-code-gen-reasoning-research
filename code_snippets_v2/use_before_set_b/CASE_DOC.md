# Case: use_before_set_b

**Family:** use_before_set
**Difficulty:** B (Medium)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F5: Information bias (empty/edge input is invisible path)

---

## Task Prompt

> Pipeline crashes on empty data source. Fix. Return the updated code.

## What the Code Does

A two-file pipeline system. `loader.py` loads data from a source and tracks status. `pipeline.py` calls the loader and returns a status-tagged result.

**loader.py:**
```python
_status = "idle"
_data = None

def load(source):
    global _status, _data
    if source and len(source) > 0:
        _data = [x for x in source]
        _status = "loaded"
    # BUG: on empty/None source, _status stays at previous value
    return _data
```

**pipeline.py:**
```python
def run_pipeline(source):
    load(source)
    status = get_status()
    data = get_data()
    return {
        "status": status,
        "count": len(data) if data else 0,
        "data": data,
    }
```

The contract: `status` in the returned dict must reflect THIS call's outcome. After loading empty data, status should not be "loaded."

## The Bug

In `loader.py`, `_status` is only set to `"loaded"` inside the `if source and len(source) > 0:` block. When the source is empty, `_status` retains whatever value it had from a previous call. If a previous call loaded data successfully, `_status` is still `"loaded"` even though the current call loaded nothing.

`pipeline.py` reads `get_status()` unconditionally and trusts whatever the loader reports. There is no independent check -- the pipeline inherits the stale status.

## The Correct Fix

Set `_status` to `"empty"` (or `"idle"`) when source is empty:

```python
def load(source):
    global _status, _data
    if source and len(source) > 0:
        _data = [x for x in source]
        _status = "loaded"
    else:
        _data = None
        _status = "empty"
    return _data
```

**Lines changed:** 1-3 (add else-branch that resets `_status` and `_data`)

## What the Test Checks

1. Reset module state (`_status = "idle"`, `_data = None`)
2. Call `run_pipeline([10, 20, 30])` -- first call loads data, sets status to "loaded"
3. Call `run_pipeline([])` -- second call with empty data
4. **Assert:** `r2["status"] != "loaded"` -- status must not leak from previous call
5. **Assert:** `r2["count"] == 0` -- count must reflect empty input

## Why This Is Difficult for LLMs

- **Cross-file stale state:** The bug is in `loader.py` but manifests through `pipeline.py`. The model must trace the `get_status()` call across the file boundary to understand that the loader's stale `_status` propagates.
- **The loader looks like it "handles" empty input:** It returns `_data` (which is `None` initially), so the return value is technically correct for empty input. The status leakage is a secondary, silent failure.
- **Distractor function:** `validate_format()` in `loader.py` checks data format and returns `False` for `None`, looking like a potential fix point. But the bug is in `load()`, not in validation.
- **Information bias (F5):** Models trained on typical load/process patterns rarely see empty-source scenarios. The "load succeeds" path dominates training data.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason about an intervention: "If I add an else-branch in `load()` that resets `_status`, then `get_status()` in `pipeline.py` would return the correct value." This requires understanding the causal chain from loader state to pipeline output across the file boundary.

### Trap Type: F5: Information bias (empty/edge input is invisible path)

The empty-source path is invisible in typical usage. Models associate `load(source)` with success. The fact that `_status` persists across calls is a hidden dependency that only manifests when the invisible (empty) path is exercised after a successful call.

### Why This Case Is L2, Not L1 or L3

**Not L1** because the bug is in `loader.py` but the invariant ("status must reflect this call") is enforced in `pipeline.py`. Understanding the failure requires tracing the `get_status()` call across one file boundary.

**Not L3** because there is only one cross-file dependency to trace (loader -> pipeline). No multi-step state evolution or multiple interacting modules are involved.

## Failure Mode Being Tested

**USE_BEFORE_SET** (edge_case_omission) -- module-level state is set only on the success path. When the edge case (empty input) occurs, stale state from a previous call leaks through to consumers.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace stale state across file boundary |
| 4o-mini | REI | May identify the status issue but fix it in pipeline instead of loader |
| 5-mini | CSF | Should trace the cross-file dependency and fix the loader |
