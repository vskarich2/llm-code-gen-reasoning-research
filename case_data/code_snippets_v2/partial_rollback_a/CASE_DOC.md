# Case: partial_rollback_a

**Family:** partial_rollback
**Difficulty:** A (Easy)
**Bug Pattern:** partial_state_update
**Causal Depth:** L1
**Pearl Level:** L1 Association
**Trap Type:** F1: Selection (happy-path bias, failure path invisible)

---

## Task Prompt

> Refactor this order system for clarity. Return the updated code.

## What the Code Does

A single-file order fulfillment system (`order.py`) with two classes (`Inventory`, `Wallet`) and a `place_order` function that coordinates a two-step transaction.

```python
class Inventory:
    def reserve(self, qty):
        if qty > self.stock - self.reserved:
            raise ValueError("insufficient stock")
        self.reserved += qty

    def release(self, qty):
        self.reserved -= qty

class Wallet:
    def charge(self, amount):
        if amount > self.balance:
            raise ValueError("insufficient funds")
        self.balance -= amount

def place_order(inventory, wallet, qty, price):
    inventory.reserve(qty)
    try:
        wallet.charge(qty * price)
    except ValueError:
        raise  # BUG: re-raises without releasing inventory reservation
    return {"status": "confirmed", "qty": qty, "total": qty * price}
```

The two-step sequence: (1) reserve inventory, (2) charge wallet. If step 2 fails (insufficient funds), the reservation from step 1 should be rolled back.

## The Bug

When `wallet.charge()` raises `ValueError` (insufficient funds), the `except` clause re-raises the exception without calling `inventory.release()` first. The inventory reservation persists even though no payment was made. `inventory.available()` returns a value lower than it should.

The `try/except` block looks like it handles the error -- it catches the exception. But it performs **no compensation** for the side effect of `reserve()` before re-raising.

## The Correct Fix

Add `inventory.release(qty)` before re-raising:

```python
def place_order(inventory, wallet, qty, price):
    inventory.reserve(qty)
    try:
        wallet.charge(qty * price)
    except ValueError:
        inventory.release(qty)  # rollback reservation
        raise
    return {"status": "confirmed", "qty": qty, "total": qty * price}
```

**Lines changed:** 4 (add rollback call, restructure except block)

## What the Test Checks

1. Create `Inventory(10)` and `Wallet(0)` (zero balance ensures charge fails)
2. Call `place_order(inv, wallet, 3, 10.0)` -- expect `ValueError`
3. **Assert:** `inv.available() == 10` -- reservation was rolled back
4. **Assert:** `inv.reserved == 0` -- no lingering reservation

## Why This Is Difficult for LLMs

- **Task says "refactor," not "fix."** The model is not told there is a bug. It may reorganize code without noticing the missing rollback.
- **Happy-path bias (F1):** Training data overwhelmingly shows successful transactions. The failure path (charge fails after reserve) is underrepresented. Models associate `place_order` with the success case.
- **The try/except looks correct:** It catches the error. The pattern `try: ... except: raise` is a common pass-through pattern. The model must recognize that this pass-through needs compensation for a prior side effect.
- **Common wrong fix:** Moving `reserve()` inside the try block (changes the error semantics) or removing the try/except (loses the re-raise behavior).

## Causal Reasoning Required (L1)

### Pearl Level: L1 Association

The entire bug is visible in one function in one file. `reserve()` mutates `self.reserved`, and the `except` block re-raises without calling `release()`. The classes and their methods are all in the same file. The model needs only to associate the `reserve()` side effect with the need for compensation on failure.

### Trap Type: F1: Selection (happy-path bias, failure path invisible)

The F1 selection bias makes the failure path invisible. When asked to "refactor for clarity," models default to the happy path (reserve succeeds, charge succeeds, return confirmed). The failure path (charge fails after reserve) is never the "main story" in training data.

### Why This Case Is L1, Not L2 or L3

**Not L2** because `Inventory`, `Wallet`, and `place_order` are all in the same file. No cross-file reasoning is needed. The `reserve()` and `release()` methods are defined directly above `place_order`.

**Not L3** because there is only one resource to compensate (inventory reservation) and no multi-step state evolution. The fix is a single rollback call.

## Failure Mode Being Tested

**PARTIAL_ROLLBACK** (partial_state_update) -- a multi-step operation commits step 1 before validating step 2. When step 2 fails, step 1 is not compensated, leaving the system in an inconsistent state.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | REI | May describe the rollback need but not implement it |
| 4o-mini | Heuristic | Likely to notice try/except but may not add release call |
| 5-mini | CSF | Should identify the missing rollback in single-file context |
