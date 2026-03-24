# Case: early_return_a

**Family:** early_return
**Difficulty:** A (Easy)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F4: Post hoc fallacy (temporal sequence != causation)

---

## Task Prompt

> Refactor this payment processor for clarity. Return the updated code.

## What the Code Does

A single-file payment processor in `payment.py` with a module-level ledger:

```python
_ledger = []

def process_payment(amount, description="payment"):
    # BUG: early return skips ledger entry for zero-amount payments
    if amount == 0:
        return {"status": "skipped", "amount": 0}

    entry = {"amount": amount, "description": description, "status": "charged"}
    _ledger.append(entry)
    return {"status": "charged", "amount": amount}
```

`verify_ledger(expected_count)` checks that the ledger has exactly `expected_count` entries. The docstring explicitly states: "All payments -- including zero-amount -- must be recorded in the ledger for audit compliance."

## The Bug

When `amount == 0`, the function returns early at line 15 without appending anything to `_ledger`. The docstring and function contract require that every call to `process_payment` creates a ledger entry, including zero-amount payments (with status "skipped"). The early return silently breaks the audit invariant.

**Violated invariant:** Ledger/audit must have entry for every call.

## The Correct Fix

Add a ledger entry before the early return on line 15 of `payment.py`:

```python
if amount == 0:
    _ledger.append({"amount": 0, "description": description, "status": "skipped"})
    return {"status": "skipped", "amount": 0}
```

**Lines changed:** 1 (add `_ledger.append(...)` before the return)

## What the Test Checks

1. Process one normal payment (amount=100) and one zero-amount payment
2. `verify_ledger(2)` returns True -- both calls must produce ledger entries

## Why This Is Difficult for LLMs

- **Refactor framing:** The task says "refactor for clarity," not "fix a bug." A model may reorganize the code cosmetically while preserving the early-return pattern.
- **Early return looks efficient:** Returning early for zero-amount payments seems like a reasonable optimization. The model must read the docstring carefully to understand the audit requirement.
- **Post hoc trap:** The sequence "check amount, then return" seems causally complete -- the model may assume that skipping processing also means skipping recording, when in fact recording is mandatory regardless of processing.

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The bug is visible by reading the single file: the docstring says "all payments must be recorded" and the early return path does not record. This is a direct association between the contract and the code, requiring no cross-function or cross-file reasoning.

### Trap Type: F4: Post hoc fallacy (temporal sequence != causation)

The early return creates a temporal shortcut: because zero-amount payments don't need processing, the code skips everything after the check -- including the mandatory ledger recording. The model may fall into the post hoc fallacy: "zero-amount payments are skipped, therefore they don't need recording." The temporal sequence (check -> return) is mistaken for causal sufficiency, when recording is actually an independent requirement.

### Why This Case Is L1, Not L2/L3

- **Not L2:** No cross-file or cross-function tracing is needed. The bug, contract, and fix are all in `process_payment()` in a single file.
- **Not L3:** No counterfactual or multi-step reasoning is required.

## Failure Mode Being Tested

**hidden_dependency** -- The ledger recording is a hidden dependency of the early-return path. The dependency is documented in the docstring but not enforced by the code structure, making it easy to miss during refactoring.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | Likely to preserve or refactor the early return without adding ledger entry |
| 4o-mini | Heuristic | May recognize the docstring requirement but could miss the ledger append |
| 5-mini | CSF | Should identify the contract violation through docstring analysis |
