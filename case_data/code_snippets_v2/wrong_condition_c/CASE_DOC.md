# Case: wrong_condition_c

**Family:** wrong_condition
**Difficulty:** C (Hard)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F3: Simpson's paradox variant (precedence makes correct sub-expressions compose incorrectly)

---

## Task Prompt

> Expired tokens still allowed for exempt users. Fix. Return the updated code.

## What the Code Does

Three files implement a rate limiting system with expiration and exemption:

**`policy.py`** provides three predicates: `is_expired(timestamp, now, window_seconds)`, `is_under_limit(count, limit)`, and `is_exempt(client_id, exempt_list)`.

**`limiter.py`** combines the predicates:

```python
def should_allow(client_id, count, limit, timestamp, now,
                 window_seconds, exempt_list):
    expired = is_expired(timestamp, now, window_seconds)
    under_limit = is_under_limit(count, limit)
    exempt = is_exempt(client_id, exempt_list)

    # BUG: operator precedence
    # Python parses as: ((not expired) and under_limit) or exempt
    # Correct intent:   (not expired) and (under_limit or exempt)
    return not expired and under_limit or exempt
```

**`middleware.py`** wires the limiter into request processing, passing client state and default configuration (window=60s, limit=100, exempt_clients={"internal-service", "health-checker"}).

## The Bug

Python's operator precedence evaluates `not expired and under_limit or exempt` as `((not expired) and under_limit) or exempt`. The intended logic is `(not expired) and (under_limit or exempt)`.

When a token is expired (`expired=True`) AND the client is exempt (`exempt=True`):
- **Buggy:** `(False and under_limit) or True` = `True` (allows the request)
- **Correct:** `False and (under_limit or True)` = `False` (blocks the request)

Exempt clients bypass the rate limit, but expired tokens should always be rejected -- even for exempt clients.

**Violated invariant:** Boundary condition must be handled correctly.

## The Correct Fix

Add explicit parentheses on line 26 of `limiter.py`:

```python
return not expired and (under_limit or exempt)  # FIX: explicit parentheses
```

**Lines changed:** 1

## What the Test Checks

1. `should_allow(client_id="internal-service", count=200, limit=100, timestamp=0, now=100, window_seconds=60, exempt_list={"internal-service"})` returns `False` -- expired token must be rejected even for exempt clients

## Why This Is Difficult for LLMs

- **Trap: Boolean reads correctly.** The expression `not expired and under_limit or exempt` reads naturally in English as "not expired and (under the limit or exempt)," which is the correct intent. The Python precedence silently differs from the English reading.
- **Three-file context:** The model must understand the semantics of each predicate from `policy.py`, trace the composition in `limiter.py`, and understand the real-world usage from `middleware.py` to reason about which precedence is correct.
- **Exempt clients are a special case:** The model might reason that exempt clients should always be allowed (since they are "exempt"), missing the constraint that token expiration is an independent, non-bypassable check.
- **Only manifests with specific input combinations:** The bug only appears when `expired=True AND exempt=True`. Most test cases (non-exempt clients, or non-expired exempt clients) pass correctly.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform multi-step causal propagation through the boolean logic:
1. Understanding each predicate's semantics from `policy.py` (mechanism verification)
2. Evaluating Python's operator precedence in `limiter.py` (deterministic state tracing)
3. Reasoning about the design intent from `middleware.py`'s exempt list semantics (forward path analysis)
4. Tracing the specific input combination (expired + exempt) through the precedence rules to see that `((not expired) and under_limit) or exempt` evaluates differently than the intended `(not expired) and (under_limit or exempt)`

This is deterministic state tracing across three files with mechanism verification of Python's operator precedence rules.

### Trap Type: F3: Simpson's paradox variant (precedence makes correct sub-expressions compose incorrectly)

Each individual predicate (`is_expired`, `is_under_limit`, `is_exempt`) is correct. The composition expression uses the right variables and the right logical intent. But Python's operator precedence silently regroups the sub-expressions, creating a paradox where the aggregate behavior contradicts the intended policy -- each sub-check is correct, but the composition is wrong.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug is not visible from inspecting any single file. The expression looks correct to English-language reading.
- **L2 (deep):** The model must trace three predicates across three files, apply Python's operator precedence rules deterministically, and propagate the causal effect of the wrong grouping through specific input values. This is multi-step causal propagation with mechanism verification of language-level precedence rules.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. Python's operator precedence is a fixed rule; the model evaluates the expression step by step, not by comparing two hypothetical worlds.

## Failure Mode Being Tested

**edge_case_omission** -- Operator precedence creates a silent semantic error that only manifests under a specific combination of conditions (expired AND exempt). The natural-language reading of the code matches the intent, but the Python evaluation does not.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot reason about operator precedence across 3 files |
| 4o-mini | CSF | May read the expression as correct English and miss the precedence issue |
| 5-mini | CSF | Best chance but precedence + edge-case input construction is challenging |
