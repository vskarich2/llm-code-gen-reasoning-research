# Case: partial_update_c

**Family:** partial_update
**Difficulty:** C (Hard)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2 (hard)
**Pearl Level:** L2 Intervention (multi-step intervention correctness under mechanism trap)
**Trap Type:** F1 Selection: only some fields updated + F6 Mechanism: validation runs but doesn't trigger state reset

---

## Task Prompt

> After changing email, old greeting still shows. Fix the update. Return the updated code.

## What the Code Does

A three-file profile system with email verification, cached greetings, and notification/validation helpers. Changing email should reset the `verified` flag and update the `cached_greeting`, but the update function omits both side effects.

### Files

**profile.py**
- `create_user(name, email)` -- creates user with `verified=False` and `cached_greeting` built via `build_greeting()`
- `verify_user(user)` -- sets `user["verified"] = True`
- `update_profile(user, changes)` -- iterates changes; for `email`, validates via `validate_email()` and updates `user["email"]` but does NOT reset `verified` to `False` or update `cached_greeting`; for `name`, correctly updates both `user["name"]` and `cached_greeting`

**validation.py**
- `validate_email(email)` -- returns True if email contains '@' and '.'
- `validate_name(name)` -- returns True if name is non-empty string

**notifications.py**
- `build_greeting(user)` -- returns `"Hello, " + user["name"] + "!"`
- `should_reverify(old_email, new_email)` -- determines if email change requires re-verification (TRAP: exists but is never called)

## The Bug

In `profile.py`, lines 30-32: when `key == "email"`, the code saves `old_email`, updates `user["email"]`, but does NOT:
1. Set `user["verified"] = False` (email changed, verification should be invalidated)
2. Update `user["cached_greeting"]` (though for email changes, the greeting doesn't include email, this is still part of the contract)

Most critically, `verified` remains `True` after an email change, violating the security invariant that changing email requires re-verification.

The `should_reverify()` function in `notifications.py` exists precisely for this purpose but is never called -- a classic case of a utility function that was written but not wired in.

## The Correct Fix

In `profile.py`, after `user["email"] = value` (line 32), add:

```python
if key == "email" and validate_email(value):
    old_email = user.get("email")
    user["email"] = value
    user["verified"] = False  # ADD: reset verification on email change
```

2 lines changed (1 added for `verified = False`).

## What the Test Checks

1. `create_user("Alice", "alice@example.com")` creates a user
2. `verify_user(user)` marks user as verified
3. Confirms `user["verified"]` is `True`
4. `update_profile(user, {"email": "bob@example.com"})` changes the email
5. `user["verified"]` must be `False` (re-verification required)
6. `user["email"]` must be `"bob@example.com"`

## Why This Is Difficult for LLMs

- The trap: `validate_email()` in `validation.py` runs during the update and returns True. An LLM might think "validation passed, so the email update is correct." But validation is about format, not about side effects.
- `should_reverify()` in `notifications.py` exists but is never called. An LLM might see it and either (a) think it is already called somewhere, or (b) try to wire it in without understanding that the simpler fix is just setting `verified = False`.
- The `old_email` variable is captured on line 31 but never used for anything. This dead code suggests the developer intended to add reverification logic but forgot.
- The `name` update branch correctly syncs `cached_greeting`, creating a false sense that all branches handle their side effects. The asymmetry between `name` (correct) and `email` (incomplete) is the core issue.
- Three files create cognitive load. The LLM must determine which file(s) need changes.

## Causal Reasoning Required (L2, Hard)

### Pearl Level: L2 Intervention (Multi-Step Intervention Correctness Under Mechanism Trap)

This requires L2 intervention reasoning: the model must determine the correct intervention (add `verified = False` after email write in `profile.py`) by tracing the update path across three files and recognizing that the validator (`validate_email`) and the utility function (`should_reverify`) are mechanism traps — they look like they handle the state transition but don't.

The reasoning is deterministic: trace what `update_profile` does for the `"email"` key, observe that `validated = True` and `user["email"]` is updated, but `user["verified"]` is not reset. The model must know that changing email invalidates prior verification — this is a domain-level invariant, not a code-structural one. But identifying and implementing the fix does not require simulating alternative execution paths or counterfactual worlds. It requires correctly identifying **where to intervene** in a multi-file system where the obvious intervention targets (validator, reverify utility) are traps.

### Trap Type: F1 Selection + F6 Mechanism

**F1 Selection**: The update function handles some fields completely (name syncs greeting) but others incompletely (email doesn't reset verified). The selection of which side effects to perform is incomplete.

**F6 Mechanism**: `validate_email` runs and succeeds, giving the appearance that the email update mechanism is complete. But the validation mechanism only checks format, not state consistency. The `should_reverify()` function represents the correct mechanism that should be invoked but isn't — it is defined but not wired into the causal path. These are mechanism traps: they look like the right place to intervene but aren't.

### Why This Case Is L2 (Hard), Not L1 or L3

- Not L1 because the bug requires understanding three files and the relationship between email changes and verification status. Pattern matching doesn't help — there is no common "reset verified on email change" idiom in training data.
- L2 (hard) because the model must determine the correct intervention point in a multi-file system with two mechanism traps (validator that checks format only, utility function that exists but isn't called). The difficulty is in intervention correctness — choosing the right fix among plausible alternatives — not in the reasoning type.
- **Not L3** because no counterfactual world simulation is required. The update path is deterministic: trace what happens when `key == "email"`, observe the missing side effect, add it. The temporal sequence (create → verify → update) provides context but the model doesn't need to simulate alternative execution paths — it just needs to see that `verified` should be reset and implement that directly.

## Failure Mode Being Tested

Partial state update with cross-boundary hidden dependencies. The `verified` flag depends on `email` but this dependency is not enforced in the update path. This tests whether the model can identify missing state transitions in a multi-file system with validation and notification layers that look complete but aren't.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Unlikely to trace the three-file dependency chain or understand verification semantics |
| 4o-mini | CSF | May focus on validation.py or try to wire in should_reverify rather than the simpler fix |
| 5-mini | CSF | Best chance but may still be distracted by the unused should_reverify function |

*These are hypotheses, not measurements.*
