# Case: missing_branch_c

**Family:** missing_branch
**Difficulty:** C (Hard)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1: Selection (unrepresented subgroup in conditional)

---

## Task Prompt

> Service accounts denied despite middleware allowing. Fix. Return the updated code.

## What the Code Does

Three files form a layered access-control pipeline:

**`roles.py`** defines `ROLE_TYPES = {"admin", "user", "moderator", "service_account", "guest"}` and provides `get_role_level()` and `is_valid_role()`. The `service_account` role has privilege level 80.

**`middleware.py`** validates requests and attaches role context. `authenticate()` correctly recognizes `service_account` as an elevated role:

```python
if role in ("admin", "service_account", "moderator"):
    return {"role": role, "allowed": True, "elevated": True}
```

**`auth.py`** contains `authorize(request)` which calls `middleware.authenticate()` then dispatches on the role:

```python
if role == "admin": ...
elif role == "moderator": ...
elif role == "user": ...
elif role == "guest": ...
else:
    # Unknown role -- no access
    return {"can_read": False, "can_write": False, "can_admin": False}
```

The `service_account` role passes middleware authentication (allowed=True, elevated=True) but falls into the `else` branch in `authorize()`, getting zero permissions.

## The Bug

`auth.py::authorize()` handles admin, moderator, user, and guest but has no branch for `service_account`. The middleware correctly allows service accounts through (setting `allowed=True`), but the authorization handler treats them as unknown, returning all-False permissions.

**Violated invariant:** All valid roles must receive correct permissions.

## The Correct Fix

Add a `service_account` branch in `auth.py::authorize()` (between the admin and moderator checks):

```python
elif role == "service_account":  # FIX: added service_account branch
    return {"can_read": True, "can_write": True, "can_admin": False}
```

**Lines changed:** 2

## What the Test Checks

1. `authorize({"role": "service_account"})` returns `can_read` = True
2. `authorize({"role": "service_account"})` returns `can_write` = True
3. `authorize({"role": "service_account"})` returns `can_admin` = False

## Why This Is Difficult for LLMs

- **Trap: Fix middleware only.** A model might see that middleware handles service_account and conclude the fix should be there. But middleware is already correct -- the bug is in auth.py's handler.
- **Three-file reasoning:** The model must trace service_account through roles.py (valid role) -> middleware.py (allowed=True) -> auth.py (falls to else). This is a multi-hop cross-boundary chain.
- **Middleware masks the bug:** Because middleware returns `allowed=True` for service_account, the denial happens silently in a later stage. The model must not stop at the middleware success.
- **Permission assignment ambiguity:** The model must decide what permissions service_account should have. The role level (80, between admin=100 and moderator=60) and the pattern of other roles suggest read+write but not admin.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through the entire request pipeline: trace `service_account` from `roles.py` (valid role, level 80) through `middleware.py` (allowed=True, elevated=True) into `auth.py`'s `authorize()` function, where it falls into the `else` branch and receives all-False permissions. This is deterministic state tracing across modules -- multi-step causal propagation following the request through three layers to identify the missing branch. The model verifies the mechanism at each layer to understand that middleware's decision is necessary but not sufficient.

### Trap Type: F1: Selection (unrepresented subgroup in conditional)

The `authorize()` function's if/elif chain is a selection mechanism over roles. `service_account` is a valid, recognized role (present in ROLE_TYPES, handled by middleware) but is unrepresented in the authorization handler's selection logic. The selection gap spans a cross-boundary pipeline.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug is not visible from any single file. roles.py is correct, middleware.py is correct -- only auth.py is wrong, but understanding why requires the full pipeline context.
- **L2 (deep):** The model must trace the request through three files (roles -> middleware -> auth), verify the mechanism at each layer, and identify the missing branch in the `authorize()` if/elif chain. This is multi-step causal propagation across module boundaries with mechanism verification at each hop.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The role validation, middleware decision, and if/elif dispatch are all directly observable from tracing the actual execution path forward.

## Failure Mode Being Tested

**edge_case_omission** -- A valid input category passes early validation stages but is silently dropped at a later stage due to an incomplete conditional. The multi-layer pipeline makes the omission harder to detect because each layer independently appears correct.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the 3-file pipeline; likely to attempt fixes in the wrong file |
| 4o-mini | CSF | May identify the pipeline but fix middleware instead of auth.py, or assign wrong permissions |
| 5-mini | CSF | Best chance of tracing the full pipeline, but permission assignment is ambiguous |
