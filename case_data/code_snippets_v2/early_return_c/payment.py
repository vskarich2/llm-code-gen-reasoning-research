

from ledger import record, get_count, reset_ledger
from audit import log_charge, verify_completeness, get_log, reset_audit

_charge_cache = {}


def charge(txn_id, amount):
    if txn_id in _charge_cache:
        return _charge_cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    log_charge(txn_id, amount)
    _charge_cache[txn_id] = result
    return result


def refund(txn_id):
    if txn_id not in _charge_cache:
        return {"txn_id": txn_id, "status": "not_found"}
    original = _charge_cache[txn_id]
    record(txn_id, -original["amount"], "refund")
    log_charge(txn_id, -original["amount"], source="refund")
    return {"txn_id": txn_id, "status": "refunded"}


def reset():
    global _charge_cache
    _charge_cache = {}
    reset_ledger()
    reset_audit()
