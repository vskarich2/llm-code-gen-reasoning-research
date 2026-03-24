# Case: partial_rollback_c

**Family:** partial_rollback
**Difficulty:** C (Hard)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F1: Selection (happy-path bias, failure path invisible)

---

## Task Prompt

> Inventory and audit corrupted after payment failure. Fix. Return the updated code.

## What the Code Does

A three-file order system with three sequential steps: reserve inventory, log audit entry, process payment.

**inventory.py** manages stock and reservations (`reserve()`, `release()`, `available()`, `get_reserved()`).

**payment.py** handles payment processing and maintains an audit log:
```python
def process(amount, order_id):
    if _gateway_fail:
        raise ValueError("payment declined")
    return {"paid": amount, "order_id": order_id}

def add_audit_entry(entry):
    _audit_log.append(entry)

def remove_audit_entry(order_id):
    global _audit_log
    _audit_log = [e for e in _audit_log if e.get("order_id") != order_id]
```

**order_service.py** coordinates the three-step flow:
```python
def place_order(product_id, qty, price):
    order_id = f"ORD-{product_id}-{qty}"
    reserve(product_id, qty)                    # Step 1: mutates _reserved
    add_audit_entry({"order_id": order_id, ...}) # Step 2: mutates _audit_log
    try:
        result = process(qty * price, order_id)  # Step 3: may fail
    except ValueError:
        raise  # BUG: re-raises without rolling back reservation OR audit entry
    _notifications.append(...)
    return {"status": "confirmed", "payment": result}
```

A distractor function `retry_payment()` exists in `order_service.py` that retries the payment gateway -- using this function would leave partial state (reservation + audit) corrupted across retries.

## The Bug

When `process()` raises (payment declined), the `except` clause re-raises without compensating **either** of the two preceding side effects:
1. `reserve()` mutated `_reserved` in `inventory.py` -- needs `release()`
2. `add_audit_entry()` added an entry to `_audit_log` in `payment.py` -- needs `remove_audit_entry()`

Both resources must be rolled back. The bug is a **compound** partial state update: two separate modules have been mutated before the failing step.

## The Correct Fix

Add both rollback operations before re-raising:

```python
def place_order(product_id, qty, price):
    order_id = f"ORD-{product_id}-{qty}"
    reserve(product_id, qty)
    add_audit_entry({"order_id": order_id, "product": product_id, "qty": qty})
    try:
        result = process(qty * price, order_id)
    except ValueError:
        release(product_id, qty)          # rollback inventory
        remove_audit_entry(order_id)      # rollback audit log
        raise
    _notifications.append({"order_id": order_id, "status": "confirmed"})
    return {"status": "confirmed", "payment": result}
```

**Lines changed:** ~11 (add two rollback calls, restructure except block)

## What the Test Checks

1. Add 20 units of product WIDGET-1
2. Set payment gateway to fail
3. Call `place_order("WIDGET-1", 5, 10.0)` -- expect `ValueError`
4. **Assert:** `available("WIDGET-1") == 20` -- reservation rolled back
5. **Assert:** `len(get_audit_log()) == 0` -- audit entry removed on rollback

## Why This Is Difficult for LLMs

- **Two resources to rollback:** The model must identify BOTH `reserve()` and `add_audit_entry()` as side effects that need compensation. Fixing only one leaves the system partially corrupted.
- **Three files to trace:** `order_service.py` calls functions from both `inventory.py` and `payment.py`. The model must understand the side effects in each.
- **Trap: retry_payment()** in `order_service.py` looks like a "fix" -- retry the payment instead of rolling back. But retrying without rollback leaves the reservation and audit entry in place, and if the retry fails again, the state is still corrupted.
- **The audit rollback is easy to miss:** Models often identify the inventory rollback (it is the more common pattern) but forget that `add_audit_entry()` also needs compensation via `remove_audit_entry()`.
- **Happy-path bias (F1):** The success path (reserve -> audit -> pay -> notify) is the dominant pattern in training data. The compound-failure path is rare.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through the failure path: trace `place_order` step by step -- `reserve()` mutates `_reserved`, `add_audit_entry()` mutates `_audit_log`, then `process()` raises. The model must then verify the mechanism in the `except` clause: it re-raises without calling `release()` or `remove_audit_entry()`. This is deterministic state tracing across modules -- multi-step causal propagation identifying two independent state mutations that need compensation on the failure path.

### Trap Type: F1: Selection (happy-path bias, failure path invisible)

The happy-path bias is compounded by the multi-resource rollback requirement. Even if the model recognizes the failure path exists, it may only roll back one resource (the more obvious inventory reservation) and miss the other (the audit log entry). The `retry_payment` distractor further biases toward "fix by retrying" rather than "fix by rolling back."

### Why This Case Is L2 (deep), Not L1 or L3

**Not L1** because the bug spans three files and two independent side effects. No single-file analysis reveals the compound rollback requirement.

**L2 (deep)** because the model must trace two separate causal chains across three files (inventory mutation + audit mutation), recognize both need rollback on the failure path, and reject the `retry_payment` distractor. This is multi-step causal propagation with mechanism verification at each mutation point.

**Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The state mutations, the exception path, and the missing rollback calls are all directly observable from tracing the actual execution flow.

## Failure Mode Being Tested

**PARTIAL_ROLLBACK** (partial_state_update) -- a multi-step operation commits two side effects before a failing step. Both side effects must be compensated on failure. The compound rollback requirement across three files tests the model's ability to enumerate and undo all intermediate state changes.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace compound rollback across 3 files |
| 4o-mini | CSF | May fix inventory rollback but miss audit rollback |
| 5-mini | CSF | Compound rollback with distractor is near the capability boundary |
