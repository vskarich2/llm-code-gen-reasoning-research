"""Transaction ledger — records all financial events."""

_entries = []


def record(txn_id, amount, status):
    """Record a transaction."""
    _entries.append({
        "txn_id": txn_id,
        "amount": amount,
        "status": status,
    })


def get_total():
    """Return the sum of all entry amounts."""
    return sum(e["amount"] for e in _entries)


def get_count():
    """Return the number of ledger entries."""
    return len(_entries)


def reset_ledger():
    """Clear all ledger entries."""
    _entries.clear()
