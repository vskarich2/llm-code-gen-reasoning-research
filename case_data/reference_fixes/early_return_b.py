"""Payment processor with duplicate detection."""

from ledger import record, verify, reset_ledger

_cache = {}


def process_payment(txn_id, amount):
    """Process a payment. Detects duplicates via txn_id cache.

    Every call — including duplicates — must be recorded in the ledger
    so that verify() counts match total process_payment calls.
    """
    # FIX: record ledger entry even for duplicates
    if txn_id in _cache:
        record(txn_id, amount, "duplicate")
        return _cache[txn_id]

    result = {"txn_id": txn_id, "amount": amount, "status": "charged"}
    record(txn_id, amount, "charged")
    _cache[txn_id] = result
    return result


def get_cached(txn_id):
    """Retrieve a cached payment result."""
    return _cache.get(txn_id)


def reset():
    """Reset payment state."""
    _cache.clear()
    reset_ledger()
