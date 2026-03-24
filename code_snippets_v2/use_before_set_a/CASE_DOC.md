# Case: use_before_set_a

**Family:** use_before_set
**Difficulty:** A (Easy)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F5: Information bias (empty/edge input is invisible path)

---

## Task Prompt

> Refactor this data transform for clarity. Return the updated code.

## What the Code Does

A single-file data transformation module (`transform.py`) with a `transform()` function that doubles each element in the input list and caches the result in `_last_result`.

```python
_last_result = []

def transform(data):
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    # BUG: when data is empty/falsy, returns stale _last_result
    return _last_result
```

When `data` is non-empty, a fresh `result` list is built and cached. When `data` is empty or falsy, the `if` branch is skipped entirely, and the function returns whatever `_last_result` held from a previous call.

## The Bug

When `data` is empty (`[]`), the function skips the `if data:` block and returns `_last_result`, which contains the result from the previous call. This is a classic "use before set on a conditional path" bug: the variable `_last_result` is only updated when input is non-empty, but is always returned.

The bug is silent -- no exception, no wrong type -- the function returns a valid list. But it returns **stale data**, violating the contract that each call should return a fresh result for its input.

## The Correct Fix

Initialize `_last_result` to an empty list when `data` is falsy:

```python
def transform(data):
    global _last_result
    if data:
        result = []
        for item in data:
            result.append(item * 2)
        _last_result = result
    else:
        _last_result = []
    return _last_result
```

**Lines changed:** 1-2 (add `else: _last_result = []` branch)

## What the Test Checks

1. Call `transform([1, 2, 3])` -- populate stale state
2. Call `transform([])` -- empty input
3. **Assert:** `transform([]) == []` -- must return empty list, not stale `[2, 4, 6]`

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model may reorganize the code without noticing the empty-input path is broken.
- **Information bias (F5):** Training data overwhelmingly shows non-empty inputs. The empty-input code path is rarely exercised in examples, making it invisible to pattern-matching approaches.
- **The code looks correct for non-empty input.** A model testing only the happy path would see correct behavior and conclude the code is fine.
- **Common wrong fix:** Removing the caching entirely (changes the API contract) or adding a check for `None` but not for `[]`.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible within a single function body. Reading the `if data:` guard and the unconditional `return _last_result` reveals the problem through local pattern matching: the conditional sets `_last_result` only when data is truthy, but the return always uses it.

### Trap Type: F5: Information bias (empty/edge input is invisible path)

The F5 trap works because empty inputs are underrepresented in training data. Models associate `transform(data)` with the common case where `data` contains elements. The edge case where `data` is `[]` is an invisible path -- the model never "sees" it unless it explicitly traces the conditional branch.

### Why This Case Is L1, Not L2 or L3

**Not L2** because the entire bug -- the conditional guard, the missing else-branch, and the stale return -- is in one function in one file. No cross-function reasoning is needed.

**Not L3** because there is no multi-step state evolution. The stale-state behavior is a single-step consequence of skipping the `if` block.

## Failure Mode Being Tested

**USE_BEFORE_SET** (edge_case_omission) -- a variable is conditionally set but unconditionally read. The empty-input edge case exposes stale state from a previous invocation.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May describe the empty-input issue but fail to produce the else-branch |
| 4o-mini | Heuristic | Likely to handle refactoring but may miss the stale-state edge case |
| 5-mini | CSF | Should identify the missing else-branch on empty input |
