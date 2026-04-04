# Case: early_return_c

**Family:** early_return
**Difficulty:** C (Hard)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2 (deep)
**Pearl Level:** L2 Intervention (deep, multi-step)
**Trap Type:** F4: Post hoc fallacy (temporal sequence != causation) + F6: Mechanism (caching mechanism conflated with audit mechanism)

---

## Task Prompt

> Audit log missing entries for cached charges. Fix. Return the updated code.

## What the Code Does

Three files form a payment processing pipeline:

**`audit.py`** provides `log_charge(txn_id, amount, source="direct")` to append to `_log`, `verify_completeness(expected_count)` to check log size, and `get_log()` for inspection.

**`ledger.py`** provides `record(txn_id, amount, status)` to append to `_entries`, plus `get_total()` and `get_count()`.

**`payment.py`** implements charge caching:

```python
def charge(txn_id, amount):
    # BUG: early return on cached path skips log_charge()
    if txn_id in _charge_cache:
        return _charge_cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    log_charge(txn_id, amount)
    _charge_cache[txn_id] = result
    return result
```

The docstring states: "EVERY call -- cached or not -- must be logged in the audit system for compliance."

## The Bug

When a cached `txn_id` is found (line 21), `charge()` returns the cached result without calling `log_charge()`. The ledger `record()` is also skipped, but the critical invariant is the audit log -- every call to `charge()` must produce an audit entry. The `refund()` function correctly calls both `record()` and `log_charge()`, showing the intended pattern.

**Violated invariant:** Ledger/audit must have entry for every call.

## The Correct Fix

Add `log_charge()` before the early return in `payment.py` (line 22):

```python
if txn_id in _charge_cache:
    log_charge(txn_id, amount, source="cached")  # FIX: log even on cached path
    return _charge_cache[txn_id]
```

**Lines changed:** 1

## What the Test Checks

1. Call `charge("txn-100", 200)` -- direct charge (logged)
2. Call `charge("txn-100", 200)` -- cached hit (should still be logged)
3. Call `charge("txn-101", 300)` -- direct charge (logged)
4. `verify_completeness(3)` returns True -- all three calls must produce audit entries

## Why This Is Difficult for LLMs

- **Trap: Caching is correct.** The cache correctly prevents double-charging. The model must understand that the cache is intentionally correct for billing but the audit log has a separate, independent completeness requirement.
- **Three-file context:** The model must understand audit.py's contract, ledger.py's role, and payment.py's caching logic to identify which side-effect is missing on the cached path.
- **Mechanism conflation (F6):** The caching mechanism and the audit mechanism serve different purposes. A model may reason that "if the charge is cached, no work is done, so no logging is needed" -- conflating the billing mechanism with the audit mechanism.
- **refund() as a contrast pattern:** The `refund()` function in the same file correctly calls both `record()` and `log_charge()`, demonstrating the expected pattern. The model must notice this contrast.

## Causal Reasoning Required (L2, Deep)

### Pearl Level: L2 Intervention (Deep / Multi-Step)

The model must perform forward path analysis through two sequential calls to `charge()`:
1. Tracing the first call through the normal path (record + log_charge) -- deterministic state tracing
2. Tracing the second call through the cached path (early return, no log_charge) -- mechanism verification
3. Counting the audit entries (2 expected, only 1 present) -- multi-step causal propagation
4. Distinguishing the caching concern (correct) from the audit concern (broken) -- mechanism verification

This is deterministic state tracing across three modules with mechanism verification at the cache boundary.

### Trap Type: F4: Post hoc fallacy + F6: Mechanism

**F4:** The early return creates a temporal shortcut where "already charged" implies "already logged," when in fact each call requires its own log entry regardless of billing status.

**F6:** The caching mechanism (avoid double-charging) is conflated with the audit mechanism (record every call). These are independent mechanisms with different invariants, but the code structure bundles them together, and the early return breaks only the audit mechanism.

### Why This Case Is L2 (deep), Not L1 or L3

- **Not L1:** The bug requires understanding three modules and their independent contracts.
- **L2 (deep):** The model must trace two sequential calls through the same function, verify the mechanism at the cache branch point, and propagate the causal effect of the early return on the audit log across three modules. This is multi-step causal propagation with mechanism verification -- the model must distinguish two independent invariants (billing vs. audit) within the same code path.
- **Not L3** because all steps are deterministic -- the model follows code paths, not alternative worlds. The cache hit, the early return, and the skipped `log_charge` call are all directly observable from tracing the actual execution forward.

## Failure Mode Being Tested

**hidden_dependency** with secondary **partial_state_update** -- The audit logging is a hidden dependency of the cached-charge path. The billing mechanism (cache) is correctly maintained, but the audit mechanism (log) is silently broken. This tests whether models can reason about independent invariants within the same code path.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the 3-file pipeline or separate billing from audit concerns |
| 4o-mini | CSF | May see caching as correct and not realize audit needs independent treatment |
| 5-mini | CSF | Best chance, but mechanism separation across 3 files is challenging |
