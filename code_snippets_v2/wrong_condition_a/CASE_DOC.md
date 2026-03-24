# Case: wrong_condition_a

**Family:** wrong_condition
**Difficulty:** A (Easy)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F2: Statistical artifact (boundary value treated incorrectly)

---

## Task Prompt

> Refactor this rate limiter for clarity. Return the updated code.

## What the Code Does

A single-file rate limiter in `limiter.py` with two functions:

```python
def is_rate_limited(count, limit):
    # BUG: uses > instead of >=
    return count > limit

def check_and_increment(current_count, limit):
    if is_rate_limited(current_count, limit):
        return True, current_count
    return False, current_count + 1
```

`is_rate_limited(count, limit)` should return True when the count has reached the limit, blocking further requests. `check_and_increment` uses it as a gate before incrementing.

## The Bug

The comparison uses `>` instead of `>=`. When `count == limit`, the function returns `False` (not rate-limited), allowing one extra request beyond the limit. For example, with `limit=5`, a count of 5 means 5 requests have already been made and should be blocked, but `5 > 5` is `False`, so the 6th request is allowed.

**Violated invariant:** Boundary condition must be handled correctly.

## The Correct Fix

Change `>` to `>=` on line 17 of `limiter.py`:

```python
return count >= limit  # FIX: uses >= so count==limit is blocked
```

**Lines changed:** 1

## What the Test Checks

1. `is_rate_limited(5, 5)` returns `True` (at the limit, should block)

## Why This Is Difficult for LLMs

- **Refactor framing:** The task says "refactor for clarity," not "fix a bug." A model focused on naming, structure, or docstrings may preserve the `>` operator.
- **Off-by-one subtlety:** The difference between `>` and `>=` is a single character. The code works correctly for all values except the exact boundary (`count == limit`).
- **Both operators "make sense":** A model reasoning about the natural language ("has the count exceeded the limit?") might keep `>` because "exceeded" can mean "gone past." The correct reading is "reached," not "exceeded."

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is identifiable by direct inspection of the comparison operator against the function's documented semantics. No cross-function tracing or intervention simulation is needed -- just recognizing that `>` allows the boundary case when `>=` is required.

### Trap Type: F2: Statistical artifact (boundary value treated incorrectly)

The `>` vs `>=` distinction is a statistical-artifact-style error: for nearly all inputs, both operators produce the same result. The bug only manifests at the exact boundary value (`count == limit`), creating an artifact where the system appears correct on aggregate testing but fails at the critical threshold.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-function or cross-file reasoning is needed. The bug is in a single comparison on a single line.
- **Not L3:** No counterfactual multi-step chain is involved. The fix is a direct operator change.

## Failure Mode Being Tested

**edge_case_omission** -- An off-by-one error in a comparison operator silently allows one extra request at the boundary. The bug is invisible for all non-boundary inputs, making it a classic edge-case omission.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to refactor naming/structure without examining operator semantics |
| 4o-mini | Heuristic | May recognize off-by-one pattern but could rationalize keeping > |
| 5-mini | CSF | Should identify the boundary condition error through operator analysis |
