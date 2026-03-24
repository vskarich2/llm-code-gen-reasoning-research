# Case: false_fix_deadlock

**Family:** concurrency
**Difficulty:** hard
**Bug Pattern:** circular lock wait (deadlock from opposite lock ordering)
**Causal Depth:** 2 deep
**Pearl Level:** L2
**Trap Type:** F6: removing locks or adding timeout are wrong fixes

---

## Task Prompt

> Fix the resource transfer system so that interleaved A-to-B and B-to-A transfers complete without deadlock, while preserving total balance.

## What the Code Does

`resources.py` implements a simulated resource transfer system with two resources ("A" and "B"), a simple lock mechanism (`_locks` dict), and deterministic step-based execution.

Transfer A-to-B locks A first, then B:

```python
def make_transfer_a_to_b_steps(amount):
    def step_lock_a():
        acquire("A")
        return "locked_A"

    def step_lock_b_and_transfer():
        acquire("B")
        _state["A"] -= amount
        _state["B"] += amount
        release("B")
        release("A")
        return "transferred_a_to_b"

    return step_lock_a, step_lock_b_and_transfer
```

Transfer B-to-A locks B first, then A (opposite order):

```python
def make_transfer_b_to_a_steps(amount):
    def step_lock_b():
        acquire("B")
        return "locked_B"

    def step_lock_a_and_transfer():
        acquire("A")  # DEADLOCK: A is held by the other transfer
        ...
```

- `sequential_transfers()`: A-to-B completes fully, then B-to-A. No deadlock.
- `interleaved_transfers()`: Step 1 locks A (for A-to-B), Step 2 locks B (for B-to-A), Step 3 A-to-B tries to lock B -- deadlock. A `RuntimeError` is raised by the `acquire` function.

## The Bug

The two transfer functions use opposite lock ordering: A-to-B acquires A then B, while B-to-A acquires B then A. Under interleaving, after step 1 (lock A) and step 2 (lock B), both resources are held by different transfers. Step 3 (A-to-B tries to lock B) fails because B is already held. This is the classic circular-wait deadlock pattern.

The violated invariant: transfers must complete without deadlock and the total balance (A + B) must remain 200.

## The Correct Fix

The reference fix (`reference_fixes/false_fix_deadlock.py`) applies two changes:

1. **Canonical lock ordering:** Both transfers acquire locks in the same order (A first, then B), regardless of transfer direction.
2. **Atomic steps:** Each transfer is a single atomic step (both locks + transfer + release), preventing interleaving between lock acquisition and transfer.

```python
def make_transfer_b_to_a_steps(amount):
    def step_atomic_transfer():
        acquire("A")  # canonical order: A first
        acquire("B")
        _state["B"] -= amount
        _state["A"] += amount
        release("B")
        release("A")
        return "transferred_b_to_a"

    def step_noop():
        return "noop"

    return step_atomic_transfer, step_noop
```

Both transfers use A-then-B ordering and are fully atomic. Under interleaving, the first atomic step completes its full lock-transfer-release cycle before the second runs, so no circular wait occurs.

## What the Test Checks

1. `sequential_transfers()` must not deadlock (no `"error"` key in result).
2. Sequential total `A + B` must equal 200.
3. `interleaved_transfers()` must not deadlock (no `"error"` key in result).
4. Interleaved total `A + B` must equal 200.

## Why This Is Difficult for LLMs

- **F6 trap: removing locks is a wrong fix.** A model might simply remove locking to avoid the deadlock, but this would violate data integrity in a real concurrent system. The test still checks balance conservation.
- **F6 trap: adding timeouts or try/except is a wrong fix.** Catching the `RuntimeError` and retrying or skipping does not fix the structural ordering problem.
- **Common wrong fix: only fixing one transfer.** A model might fix B-to-A's lock order but leave it as two steps, which still allows interleaving to cause the deadlock.
- **Two-part fix required:** Both canonical ordering AND atomicity are needed. Canonical ordering alone (without atomicity) still allows the interleaved schedule to hold one lock from each transfer simultaneously.

## Causal Reasoning Required (L2)

### Pearl Level: Intervention (deep)

This is L2 "deep" because the model must identify two coordinated interventions: (1) canonical lock ordering to prevent circular wait, and (2) atomic step consolidation to prevent interleaving between lock acquisitions. Either intervention alone is insufficient under the given step schedule.

### Trap Type: F6: removing locks or adding timeout are wrong fixes

The F6 trap here is particularly strong because the code already demonstrates the deadlock with a clear error message. The temptation is to "handle" the error (catch it, retry, remove locks) rather than fix the structural cause. The correct fix requires understanding that lock ordering is the root cause and that atomicity is needed within the step-function framework.

### Why This Case Is L2 Deep, Not L1 or L3

- **Not L1:** L1 would be recognizing "opposite lock ordering causes deadlock." The model must design the specific fix (canonical ordering + atomicity).
- **Not standard L2:** It is "L2 deep" because the fix has two necessary components. Standard L2 cases have a single intervention point.
- **Not L3:** L3 requires counterfactual reasoning about structural vs. contingent causes. Here the cause is clear (opposite ordering + non-atomic steps), and the fix is deterministic. There is no ambiguity about which factor is structural vs. contingent.

## Failure Mode Being Tested

Circular lock wait (deadlock): two actors each hold a resource the other needs, caused by inconsistent lock acquisition ordering.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | fail | Likely removes locks, adds try/except, or applies a timeout. May not understand the step-function model well enough to make steps atomic. |
| 4o-mini | partial | May fix lock ordering but leave the two-step structure, which still deadlocks under the given interleaved schedule. Or may make steps atomic without fixing ordering. |
| 5-mini | pass/partial | Should recognize canonical lock ordering. Whether it also makes steps atomic depends on how well it understands the step-function framework. |
