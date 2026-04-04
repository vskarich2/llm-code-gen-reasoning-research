"""Payment processor with caching and audit trail.

Caching is intentional: repeated charges for the same txn_id
return the cached result without re-charging. However, every
call to charge() must still be recorded in the audit log.
"""

from ledger import record, get_count, reset_ledger
from audit import log_charge, verify_completeness, get_log, reset_audit

_charge_cache = {}


def charge(txn_id, amount):
    """Charge the given amount. Uses cache to avoid double-charging.

    Caching is correct (no double-charge), but EVERY call — cached
    or not — must be logged in the audit system for compliance.
    """
    # FIX: log to audit even on cached path
    if txn_id in _charge_cache:
        log_charge(txn_id, amount, source="cached")
        return _charge_cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    log_charge(txn_id, amount)
    _charge_cache[txn_id] = result
    return result


def refund(txn_id):
    """Refund a previously charged transaction."""
    if txn_id not in _charge_cache:
        return {"txn_id": txn_id, "status": "not_found"}
    original = _charge_cache[txn_id]
    record(txn_id, -original["amount"], "refund")
    log_charge(txn_id, -original["amount"], source="refund")
    return {"txn_id": txn_id, "status": "refunded"}


def reset():
    """Reset all payment state."""
    global _charge_cache
    _charge_cache = {}
    reset_ledger()
    reset_audit()
