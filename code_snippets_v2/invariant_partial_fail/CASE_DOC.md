# Case: invariant_partial_fail

**Family:** Invariant Violation
**Difficulty:** Hard (V1)
**Bug Pattern:** INVARIANT_VIOLATION
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1 Selection + F6 Mechanism: extract a clean debit+credit helper and move all logging to a wrapper, without adding rollback

---

## Task Prompt

> The execute_transfer function has too many logging calls mixed with business logic. Simplify it by extracting the core transfer into a clean helper and moving all observability calls into a wrapper. Return the updated code.

## What the Code Does

The system has four modules implementing a transfer service:

- **models.py** defines `Account(account_id, balance)`.

- **ledger.py** appends structured entries to `_entries` for audit trail: `record_debit`, `record_credit`, `record_transfer_attempt`.

- **audit.py** appends alerts to `_alerts`: `emit_transfer_event`, `emit_failure_alert`.

- **transfer_service.py** contains the core logic:

```python
def execute_transfer(sender, receiver, amount):
    validate_transfer(sender, amount)
    record_transfer_attempt(sender.account_id, receiver.account_id, amount)
    sender.balance -= amount              # DEBIT
    record_debit(sender.account_id, amount)
    if random.random() < 0.3:             # Simulated transient failure
        emit_failure_alert(...)
        raise RuntimeError("transient failure during credit")
    receiver.balance += amount            # CREDIT
    record_credit(receiver.account_id, amount)
    emit_transfer_event(...)
```

The critical issue: between `sender.balance -= amount` (line 19) and `receiver.balance += amount` (line 29), a transient failure can occur. When it does, the sender has been debited but the receiver has NOT been credited. Money vanishes.

## The Bug

The task asks to "extract the core transfer into a clean helper and move all observability calls into a wrapper." The trap is that the model will faithfully separate logging from business logic but fail to notice the partial-failure invariant violation that already exists in the code. The "clean" refactored version will preserve the bug: debit happens, then failure occurs, no rollback, money is lost.

The invariant violated: `sender.balance + receiver.balance` must be conserved at all times. After a failed transfer, the sender loses money that the receiver never receives.

## The Correct Fix

The reference fix (`reference_fixes/invariant_partial_fail.py`) wraps the failure-prone section in a try/except that restores the sender's balance:

```python
def execute_transfer(sender, receiver, amount):
    validate_transfer(sender, amount)
    record_transfer_attempt(sender.account_id, receiver.account_id, amount)
    sender.balance -= amount
    record_debit(sender.account_id, amount)
    try:
        if random.random() < 0.3:
            emit_failure_alert(...)
            raise RuntimeError("transient failure during credit")
        receiver.balance += amount
        record_credit(receiver.account_id, amount)
    except Exception:
        sender.balance += amount          # ROLLBACK
        raise
    emit_transfer_event(...)
```

The key change: `sender.balance += amount` in the except block restores the debited amount when the credit phase fails.

## What the Test Checks

1. Creates `sender = Account("s1", 100)` and `receiver = Account("r1", 0)`, recording `initial_total = 100`.
2. Patches `random.random` to return `0.0` (always triggers the failure path since `0.0 < 0.3`).
3. Calls `execute_transfer(sender, receiver, 50)` expecting a `RuntimeError`.
4. Asserts `sender.balance + receiver.balance == initial_total` (balance conservation).

If no rollback exists, sender.balance is 50 and receiver.balance is 0, total is 50 instead of 100.

## Why This Is Difficult for LLMs

1. **Selection bias (F1):** The task frames the problem as "too many logging calls mixed with business logic." The model selects for the refactoring goal (separate concerns) and ignores the latent atomicity bug. The bug is pre-existing, not introduced by the refactoring.

2. **Mechanism ignorance (F6):** The model must understand the mechanism of partial failure: that `sender.balance -= amount` is an immediate, irrevocable mutation, and that the `raise` on line 27 exits the function before `receiver.balance += amount` executes. Without understanding this mechanism, the model cannot see why rollback is needed.

3. **The task misdirects:** The prompt says "simplify" and "extract" -- both suggest the code is functionally correct and only needs structural improvement. The model has no reason to suspect a correctness bug exists.

4. **Logging vs correctness confusion:** The audit/ledger calls look like the "noise" the task wants removed. The model focuses on moving those calls and doesn't examine the interleaving of mutations and failure points.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must reason about an intervention (refactoring the function) and its causal consequences:

1. Identify that `sender.balance -= amount` is a side effect that occurs before the potential failure point.
2. Trace forward: if `RuntimeError` is raised at line 27, execution jumps past `receiver.balance += amount`.
3. Conclude: the sender's balance is reduced but the receiver's is not -- money is destroyed.
4. Recognize that any refactored version must either make the debit-credit atomic or add compensating logic (rollback).

### Trap Type: F1 Selection + F6 Mechanism

**F1 (Selection):** The model selects the task's framing (refactor for clarity) and de-selects the latent bug (atomicity violation). The task never mentions a bug -- it says "simplify" -- so the model has no trigger to look for one.

**F6 (Mechanism):** Understanding why rollback is needed requires mechanistic reasoning about exception propagation, mutable state, and the non-atomic nature of sequential mutations. The model must understand that `balance -= amount` cannot be "un-done" by exception handling alone -- explicit compensation is required.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1 (shallow):** The bug spans the interaction between `sender.balance -= amount`, the random failure, and the missing `receiver.balance += amount`. It requires understanding control flow through exceptions across multiple mutations.
- **Not L3 (counterfactual):** The causal chain is forward-traceable: "debit happens, then exception, then no credit, therefore money lost." No counterfactual reasoning about alternative program structures is needed.
- **L2 (deep intervention):** The model must simulate what happens when the function is refactored (intervention) and trace the failure path to discover that the invariant violation persists (or is introduced by removing interleaved safety logic).

## Failure Mode Being Tested

INVARIANT_VIOLATION -- The financial conservation invariant (`sender.balance + receiver.balance == constant`) is violated when the debit succeeds but the credit fails, and no compensating rollback exists.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Will extract helper and move logging without noticing the atomicity gap |
| 4o-mini | CSF | Likely produces a clean refactoring that preserves the existing bug; no trigger to add rollback |
| 5-mini | CSF | May recognize the failure path but unlikely to add rollback when the task says "simplify" not "fix" |
