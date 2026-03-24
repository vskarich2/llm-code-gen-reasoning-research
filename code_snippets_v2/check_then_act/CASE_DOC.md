# Case: check_then_act

**Family:** concurrency
**Difficulty:** medium
**Bug Pattern:** non-atomic check-then-act (TOCTOU)
**Causal Depth:** 2
**Pearl Level:** L2
**Trap Type:** F1: check sees only one path

---

## Task Prompt

> Fix the bank so that the account balance never goes negative, even when two withdrawals are interleaved.

## What the Code Does

`bank.py` implements a bank account with non-atomic check-then-act withdrawal, simulated via deterministic step functions.

`make_withdraw_steps(name, amount)` splits a withdrawal into two closures sharing a `result` dict:

```python
def step_check():
    result["approved"] = check_balance(name, amount)
    return ("check", result["approved"])

def step_act():
    if result["approved"]:
        do_withdraw(name, amount)
    return ("act", result["approved"])
```

Two scenario functions withdraw 80 from a balance of 100:
- `sequential_withdrawals()`: check_a, act_a, check_b, act_b -- first succeeds (balance=20), second denied (balance stays 20).
- `interleaved_withdrawals()`: check_a, check_b, act_a, act_b -- both checks see balance=100, both approved, both debit, balance goes to -60 (bug).

## The Bug

In `interleaved_withdrawals()`, the step ordering is `[check_a, check_b, act_a, act_b]`. Both checks execute against balance=100, so both set `result["approved"] = True`. Then both acts execute, subtracting 80 twice: `100 - 80 - 80 = -60`.

The violated invariant: the account balance must never go negative.

## The Correct Fix

The reference fix (`reference_fixes/check_then_act.py`) combines check and act into a single atomic step:

```python
def step_check_and_act():
    """Atomic check-then-act: re-verify balance at debit time."""
    if check_balance(name, amount):
        do_withdraw(name, amount)
        result["approved"] = True
    else:
        result["approved"] = False
    return ("check_and_act", result["approved"])

def step_noop():
    return ("noop",)

return step_check_and_act, step_noop
```

Under interleaving, the first atomic step checks balance=100, debits to 20. The second atomic step checks balance=20, which is less than 80, so it is denied. Final balance: 20.

## What the Test Checks

1. `sequential_withdrawals()` must return balance 20.
2. `interleaved_withdrawals()` must not go negative (strict `< 0` check).
3. `interleaved_withdrawals()` must return exactly 20 (strict equality).

## Why This Is Difficult for LLMs

- **Common wrong fix: adding a guard in `do_withdraw`.** A model might add `if balance >= amount` inside `do_withdraw`, but the test checks for exact balance=20 in the interleaved case, so the second withdrawal must be fully denied (not just clamped to zero).
- **Common wrong fix: adding locks.** There is no threading -- all steps run sequentially via `run_steps`. Locks would have no effect.
- **The TOCTOU pattern is disguised.** The time-of-check/time-of-use gap is not between threads but between deterministic steps. The model must map the step-function abstraction to the classic TOCTOU pattern.
- **F1 trap:** The model may focus only on the "check passes" path and not realize the check result becomes stale by the time the act runs.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention

The model must reason: "If I intervene by making check-and-act atomic, the second withdrawal will see the post-debit balance and be correctly denied." This requires planning an intervention (merging steps), not just observing the failure.

### Trap Type: F1: check sees only one path

The `step_check` closure evaluates `check_balance` and stores a boolean. The model must recognize that this boolean can become stale -- the check "sees only one path" (the pre-debit state), missing the possibility that another act has already modified the balance. The trap is that the check appears correct in isolation; the bug only manifests when another actor intervenes between check and act.

### Why This Case Is L2, Not L1 or L3

- **Not L1:** L1 would be pattern-matching "check-then-act is a known anti-pattern." The model must actually design the correct atomic combination, not just label the pattern.
- **Not L3:** L3 requires reasoning about structural vs. contingent causation or multiple independently necessary fixes. Here there is one intervention point: merge check and act. No multi-factor reasoning is needed.

## Failure Mode Being Tested

Non-atomic check-then-act (TOCTOU): a validity check becomes stale because the state changes between the check and the subsequent action.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely adds a balance guard in `do_withdraw` or tries thread locks. Unlikely to merge steps correctly. |
| 4o-mini | partial | May recognize TOCTOU but add a redundant check in `step_act` rather than merging into a single atomic step. This could pass the test but miss the structural fix. |
| 5-mini | pass | Should recognize the need for atomic check-and-act and produce a correct merge. |
