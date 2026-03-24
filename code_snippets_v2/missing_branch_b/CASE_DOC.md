# Case: missing_branch_b

**Family:** missing_branch
**Difficulty:** B (Medium)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1: Selection (unrepresented subgroup in conditional)

---

## Task Prompt

> Guest users get no access. Fix the role dispatch. Return the updated code.

## What the Code Does

Two files collaborate to provide role-based access control:

**`roles.py`** defines access-level functions for each role, including `guest_access()` which returns `{"read": True, "write": False, "delete": False}`.

**`auth.py`** has a dispatch table mapping role strings to handler functions:

```python
_ROLE_DISPATCH = {
    "admin": admin_access,
    "user": user_access,
    "moderator": moderator_access,
    # BUG: "guest" missing -- falls through to _default_access (no access)
}
```

`get_access(role)` uses `.get(role, _default_access)` to dispatch. When `"guest"` is looked up, it silently falls to `_default_access()` which returns all-False (no access), even though `guest_access()` is imported and available.

## The Bug

The `_ROLE_DISPATCH` dictionary in `auth.py` includes admin, user, and moderator but omits `"guest"`. The `guest_access` function is imported at line 3 but never wired into the dispatch table. When `get_access("guest")` is called, it falls through to `_default_access()`, giving guests zero access instead of read-only access.

**Violated invariant:** All valid roles must receive correct permissions.

## The Correct Fix

Add `"guest"` to `_ROLE_DISPATCH` in `auth.py` (line 11):

```python
"guest": guest_access,  # FIX: added guest to dispatch table
```

**Lines changed:** 2 (one new dict entry)

## What the Test Checks

1. `get_access("guest")` returns a dict with `read` = True
2. `get_access("guest")` returns a dict with `write` = False
3. `get_access("guest")` returns a dict with `delete` = False

## Why This Is Difficult for LLMs

- **Distractor: `validate_role` exists but doesn't fix dispatch.** The `roles.py` file defines the `guest_access` function correctly. A model might look at roles.py, see it is correct, and conclude no fix is needed.
- **Cross-file reasoning required:** The bug is in `auth.py`'s dispatch table, not in the role definition. The model must trace the call from `get_access` -> `.get()` -> `_default_access` to understand why guest gets no access.
- **Import already present:** `guest_access` is already imported in `auth.py` line 3, making the fix a single-line addition to the dispatch dict. But the model must recognize the gap between "imported" and "wired up."

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens if I call `get_access('guest')`?" This requires tracing through the dispatch table lookup in `auth.py`, recognizing the fallthrough to `_default_access`, and understanding that the fix must be applied to the dispatch dict -- not to the role definitions in `roles.py`.

### Trap Type: F1: Selection (unrepresented subgroup in conditional)

The `_ROLE_DISPATCH` dictionary selects which roles get proper access handlers. The "guest" subgroup is unrepresented despite having a correctly-defined handler function (`guest_access`) that is already imported. The selection mechanism silently excludes a valid input.

### Why This Case Is L2, Not L1/L3

- **Not L1:** Simple association (inspecting one file) is insufficient. The model must cross from `auth.py` to `roles.py` to understand that `guest_access` exists and is correct, and that the dispatch table is the problem.
- **Not L3:** No multi-step temporal chain or counterfactual reasoning across multiple execution paths is required. The intervention is a single cross-function trace: call -> dispatch -> fallback.

## Failure Mode Being Tested

**edge_case_omission** -- A valid role is silently dropped by an incomplete dispatch table, despite the handler function being correctly implemented and imported. The gap between "defined" and "connected" is the core failure surface.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Likely to miss the cross-file dispatch gap or try to fix roles.py instead |
| 4o-mini | REI | May focus on roles.py (which is correct) rather than the dispatch table in auth.py |
| 5-mini | CSF | Should trace the dispatch mechanism and identify the missing entry |
