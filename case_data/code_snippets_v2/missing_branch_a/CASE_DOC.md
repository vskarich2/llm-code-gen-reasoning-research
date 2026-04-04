# Case: missing_branch_a

**Family:** missing_branch
**Difficulty:** A (Easy)
**Bug Pattern:** edge_case_omission
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1: Selection (unrepresented subgroup in conditional)

---

## Task Prompt

> Refactor this access control for clarity. Return the updated code.

## What the Code Does

A single-file permission system maps roles to permission sets via a `ROLE_PERMISSIONS` dictionary in `permissions.py`:

```python
ROLE_PERMISSIONS = {
    "admin": {"read", "write", "delete", "manage_users"},
    "user": {"read", "write"},
    # BUG: "moderator" role is missing -- falls through to empty set
}
```

`get_permissions(role)` looks up the role with `.get(role, set())`, and `has_permission(role, action)` checks membership in the returned set.

## The Bug

The `ROLE_PERMISSIONS` dictionary handles `"admin"` and `"user"` but omits `"moderator"`. When a moderator is looked up, `.get()` silently returns the default `set()`, giving them zero permissions. There is no error, no exception -- the moderator simply gets an empty permission set.

**Violated invariant:** All valid roles must receive correct permissions.

## The Correct Fix

Add the `"moderator"` entry to `ROLE_PERMISSIONS` (line 6 in `permissions.py`):

```python
"moderator": {"read", "write", "delete"},  # FIX: added moderator role
```

**Lines changed:** 2 (one new dict entry + trailing structure)

## What the Test Checks

1. `get_permissions("moderator")` returns a non-empty set
2. The returned set includes `"read"`
3. The returned set includes `"delete"`

## Why This Is Difficult for LLMs

- **Refactor framing hides the bug:** The task says "refactor for clarity," not "fix a bug." A model focused on cosmetic improvements may restructure the code without adding the missing role.
- **Silent failure:** No error or exception occurs -- `.get()` with a default quietly produces an empty set, so a model that only traces execution for crashes will miss this.
- **Plausible completeness:** With two roles already present, the dictionary looks structurally complete. The model must recognize that the domain requires a third role that is not present.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is directly observable by inspecting the dictionary keys against the set of valid roles. No intervention or counterfactual reasoning is needed -- a simple pattern-matching observation ("moderator is a valid role but is not in the dict") suffices to identify the problem.

### Trap Type: F1: Selection (unrepresented subgroup in conditional)

The `ROLE_PERMISSIONS` dictionary is a selection mechanism: it selects which roles receive permissions. The "moderator" subgroup is unrepresented in this selection, creating a selection bias where only admin and user roles receive correct treatment. The bug is a classic case of an incomplete enumeration in a conditional/dispatch structure.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No intervention simulation is needed. The fix does not require tracing through cross-function calls or reasoning about what would change if a function were modified.
- **Not L3:** No multi-step counterfactual chain is involved. The bug and fix are co-located in a single dictionary in a single file.

## Failure Mode Being Tested

**edge_case_omission** -- A valid input category is silently dropped by an incomplete conditional/dispatch structure. This connects to the broader taxonomy of silent-failure bugs where code appears correct on casual inspection but fails for unrepresented subgroups.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May attempt surface-level refactoring without identifying the missing role |
| 4o-mini | Heuristic | Likely recognizes the pattern of incomplete dict but may not add the right permissions |
| 5-mini | CSF | Should identify the missing moderator entry through direct dictionary inspection |
