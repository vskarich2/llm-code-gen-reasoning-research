# Case: wrong_condition_b

**Family:** wrong_condition
**Difficulty:** B (Medium)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F3: Simpson's paradox variant (each sub-check correct, composition wrong)

---

## Task Prompt

> Rate limiter allows too many requests. Fix the policy. Return the updated code.

## What the Code Does

Two files implement a rate + quota limiting system:

**`policy.py`** defines individual policy checks:

```python
def check_rate(requests_per_minute, rate_limit):
    return requests_per_minute < rate_limit

def check_quota(daily_total, daily_quota):
    return daily_total < daily_quota

def is_allowed(requests_per_minute, rate_limit, daily_total, daily_quota):
    rate_ok = check_rate(requests_per_minute, rate_limit)
    quota_ok = check_quota(daily_total, daily_quota)
    # BUG: uses 'or' instead of 'and'
    return rate_ok or quota_ok
```

**`limiter.py`** contains a `RateLimiter` class that calls `is_allowed()` to decide whether to permit requests, tracking per-minute and daily counts.

## The Bug

`is_allowed()` in `policy.py` (line 22) uses `or` instead of `and` to combine the rate and quota checks. The docstring says "allowed under BOTH rate and quota policies," but the code allows a request if EITHER condition passes. This means a client can exceed their daily quota as long as their per-minute rate is low, or exceed the per-minute rate as long as they have daily quota left.

**Violated invariant:** Boundary condition must be handled correctly -- both policies must be enforced simultaneously.

## The Correct Fix

Change `or` to `and` on line 22 of `policy.py`:

```python
return rate_ok and quota_ok  # FIX: requires BOTH conditions to pass
```

**Lines changed:** 1

## What the Test Checks

1. `is_allowed(rpm=50, rate_limit=100, daily=10001, quota=10000)` returns `False` (rate OK but quota exceeded -- should block)

## Why This Is Difficult for LLMs

- **Trap: `or` reads naturally in English.** "Is the request allowed if the rate is OK or the quota is OK?" sounds plausible in natural language. The model must override English-language intuition with logical semantics.
- **Cross-file reasoning:** The limiter class in `limiter.py` delegates to `is_allowed()` in `policy.py`. A model examining `limiter.py` alone sees a clean API call and might not dig into the policy logic.
- **Individual checks are correct:** `check_rate` and `check_quota` are each independently correct. The bug is only in how they are composed -- a Simpson's-paradox-like situation where correct sub-components produce incorrect aggregate behavior.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens when I call `is_allowed(50, 100, 10001, 10000)`?" This requires tracing from `limiter.py`'s `try_request()` into `policy.py`'s `is_allowed()`, evaluating each sub-check, and recognizing that `or` produces the wrong composite result. The intervention crosses the file boundary.

### Trap Type: F3: Simpson's paradox variant (each sub-check correct, composition wrong)

Each individual policy check (`check_rate`, `check_quota`) is correct in isolation. The error is in the aggregation operator (`or` vs `and`). This mirrors Simpson's paradox: sub-group behavior is correct, but the aggregate conclusion is reversed due to incorrect composition logic.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug cannot be found by inspecting `limiter.py` alone -- the model must cross into `policy.py` to find the `or` vs `and` error.
- **Not L3:** No multi-step counterfactual chain or temporal reasoning is needed. A single intervention trace (one call through the policy) reveals the bug.

## Failure Mode Being Tested

**edge_case_omission** -- The logical composition of two correct sub-checks uses the wrong operator, silently allowing requests that violate one of the two policies. The bug is masked by the fact that requests violating both policies are still correctly blocked.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | May not trace into policy.py or may accept 'or' as valid |
| 4o-mini | REI | Likely reads English semantics of 'or' and doesn't question it |
| 5-mini | CSF | Should trace the call and recognize the docstring vs code mismatch |
