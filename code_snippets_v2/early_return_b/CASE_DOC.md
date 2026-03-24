# Case: early_return_b

**Family:** early_return
**Difficulty:** B (Medium)
**Bug Pattern:** hidden_dependency
**Causal Depth:** L2
**Pearl Level:** L2 Intervention
**Trap Type:** F4: Post hoc fallacy (temporal sequence != causation)

---

## Task Prompt

> Ledger counts don't match transaction count. Fix. Return the updated code.

## What the Code Does

Two files implement a payment processor with duplicate detection:

**`ledger.py`** provides `record(txn_id, amount, status)` to append entries to `_entries`, plus `verify(expected_count)` that checks `len(_entries) == expected_count`, and `get_summary()` which handles empty gracefully.

**`payment.py`** uses a `_cache` dict for duplicate detection:

```python
def process_payment(txn_id, amount):
    # BUG: early return on duplicate skips record()
    if txn_id in _cache:
        return _cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    _cache[txn_id] = result
    return result
```

The docstring states: "Every call -- including duplicates -- must be recorded in the ledger so that verify() counts match total process_payment calls."

## The Bug

When a duplicate `txn_id` is detected (line 15), the function returns the cached result immediately without calling `record()`. This means `verify(n)` will fail when `n` includes duplicate calls, because the ledger only has entries for unique transactions, not for total calls.

**Violated invariant:** Ledger/audit must have entry for every call.

## The Correct Fix

Add a `record()` call before the early return in `payment.py` (line 16):

```python
if txn_id in _cache:
    record(txn_id, amount, "duplicate")  # FIX: record even for duplicates
    return _cache[txn_id]
```

**Lines changed:** 1

## What the Test Checks

1. Process txn-001 twice (second is duplicate) and txn-002 once (3 total calls)
2. `verify(3)` returns True -- all three calls must produce ledger entries

## Why This Is Difficult for LLMs

- **Trap: `ledger.get_summary` handles missing gracefully.** The ledger module does not crash on missing entries -- it just returns a lower count. The model may see the graceful handling and assume it is intentional.
- **Cross-file reasoning:** The bug is in `payment.py` but the consequence is in `ledger.py`'s `verify()`. The model must trace the data flow across files.
- **Caching is correct for its purpose:** The cache correctly prevents double-charging. The model must distinguish between "don't charge twice" (correct) and "don't record twice" (incorrect). These are separate concerns with different invariants.
- **Post hoc trap:** Because the duplicate is "already processed," the model may assume recording is also already done.

## Causal Reasoning Required (L2)

### Pearl Level: L2 Intervention

The model must simulate an intervention: "What happens when I call process_payment('txn-001', 50) twice?" This requires tracing from payment.py's cache check into the early-return path, recognizing that `record()` is skipped, and understanding that the ledger count in `ledger.py` will be wrong. The intervention crosses the file boundary between payment.py and ledger.py.

### Trap Type: F4: Post hoc fallacy (temporal sequence != causation)

The early return creates a temporal shortcut: "duplicate detected -> return cached result." The model may follow the post hoc reasoning: "the transaction was already processed, so the ledger already has an entry." But the ledger records calls, not transactions -- each call must be recorded regardless of whether the transaction was previously processed.

### Why This Case Is L2, Not L1/L3

- **Not L1:** The bug requires cross-file reasoning between payment.py and ledger.py. Reading payment.py alone, the early return looks like a correct optimization.
- **Not L3:** No multi-step counterfactual chain is needed. A single intervention (calling process_payment twice with the same txn_id) reveals the bug.

## Failure Mode Being Tested

**hidden_dependency** with secondary **partial_state_update** -- The ledger recording is a hidden dependency of the duplicate-detection path. The cache update and the ledger update are separate concerns that must both happen on every call, but the early return only preserves the cache semantics.

## Expected Regime by Model

| Model | Expected Regime | Rationale |
|---|---|---|
| nano | CSF | Cannot trace the cross-file data flow or distinguish cache from ledger semantics |
| 4o-mini | REI | May see caching as sufficient and not realize ledger needs separate recording |
| 5-mini | CSF | Should trace the duplicate path and identify the missing record() call |
