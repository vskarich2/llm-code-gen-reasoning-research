# Case: partial_rollback_b

**Family:** partial_rollback
**Difficulty:** B (Medium)
**Bug Pattern:** partial_state_update
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F1: Selection (happy-path bias, failure path invisible)

---

## Task Prompt

> Inventory stuck as reserved after payment failure. Fix. Return the updated code.

## What the Code Does

A two-file order system. `inventory.py` manages stock and reservations via module-level dicts. `order_service.py` coordinates the order flow.

**inventory.py:**
```python
def reserve(product_id, qty):
    avail = _stock.get(product_id, 0) - _reserved.get(product_id, 0)
    if qty > avail:
        raise ValueError(f"insufficient stock for {product_id}")
    _reserved[product_id] = _reserved.get(product_id, 0) + qty

def release(product_id, qty):
    _reserved[product_id] = _reserved.get(product_id, 0) - qty
```

**order_service.py:**
```python
def place_order(product_id, qty, price):
    reserve(product_id, qty)
    try:
        result = _process_payment(qty * price)
    except ValueError:
        raise  # BUG: re-raises without releasing inventory reservation
    _notifications.append({"product": product_id, "qty": qty})
    return {"status": "confirmed", "payment": result}
```

The two-step sequence: (1) reserve inventory in `inventory.py`, (2) process payment in `order_service.py`. If payment fails, inventory should be released.

## The Bug

When `_process_payment()` raises (gateway failure), the `except` clause re-raises without calling `release(product_id, qty)`. The reservation persists in `inventory.py`'s `_reserved` dict. Subsequent calls to `available()` report fewer units than actually exist.

The `_notifications` list is a distractor -- it is appended only after the `try/except`, so it is never reached on failure. The bug is not about notifications.

## The Correct Fix

Add `release()` before re-raising:

```python
def place_order(product_id, qty, price):
    reserve(product_id, qty)
    try:
        result = _process_payment(qty * price)
    except ValueError:
        release(product_id, qty)  # rollback reservation
        raise
    _notifications.append({"product": product_id, "qty": qty})
    return {"status": "confirmed", "payment": result}
```

**Lines changed:** 1 (add `release(product_id, qty)` before `raise`)

## What the Test Checks

1. Add 10 units of product SKU-100
2. Set payment gateway to fail
3. Call `place_order("SKU-100", 3, 25.0)` -- expect `ValueError`
4. **Assert:** `available("SKU-100") == 10` -- reservation was rolled back
5. **Assert:** `get_reserved("SKU-100") == 0` -- no lingering reservation

## Why This Is Difficult for LLMs

- **Cross-file side effect:** The bug is in `order_service.py`, but understanding it requires knowing that `reserve()` in `inventory.py` mutates `_reserved`. The causal chain crosses a file boundary.
- **Distractor: notifications list.** The `_notifications` list looks like it could be the issue (maybe notifications should be rolled back?), but it is never appended on the failure path. Models sometimes "fix" notification handling instead of adding the rollback.
- **try/except looks like error handling is present.** The except block exists and catches the error. The model must recognize that the handling is **incomplete** (missing compensation), not **missing** (no try/except).
- **Happy-path bias (F1):** Models trained on order processing code see the success flow. The failure-after-reserve path is rare in training data.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must reason: "If I add `release(product_id, qty)` before `raise` in `order_service.py`, the reservation mutated by `reserve()` in `inventory.py` would be undone." This requires tracing the intervention's effect across the file boundary.

### Trap Type: F1: Selection (happy-path bias, failure path invisible)

The failure path (payment declined after reservation) is invisible to models trained on successful order flows. The `_notifications` distractor reinforces the happy-path focus -- it looks like post-order housekeeping rather than a clue about rollback needs.

### Why This Case Is L2, Not L1 or L3

**Not L1** because `reserve()` is defined in `inventory.py`, separate from `order_service.py`. Understanding the side effect requires crossing one file boundary.

**Not L3** because there is only one resource to compensate (inventory reservation) and one cross-file dependency. No multi-step state evolution or multiple interacting modules.

## Failure Mode Being Tested

**PARTIAL_ROLLBACK** (partial_state_update) -- a multi-step operation that commits step 1 (reserve) before step 2 (payment) is validated. When step 2 fails, step 1's side effect is not compensated.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace cross-file state mutation |
| 4o-mini | REI | Likely identifies the rollback need but may not implement it correctly |
| 5-mini | CSF | Should trace the cross-file dependency and add release |
