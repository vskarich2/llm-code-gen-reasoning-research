"""Transaction ledger for audit tracking."""

_entries = []


def record(txn_id, amount, status):
    """Record a transaction in the ledger."""
    _entries.append({
        "txn_id": txn_id,
        "amount": amount,
        "status": status,
    })


def get_summary():
    """Return summary of all entries. Handles empty gracefully."""
    if not _entries:
        return {"count": 0, "total": 0, "entries": []}
    total = sum(e["amount"] for e in _entries)
    return {"count": len(_entries), "total": total, "entries": list(_entries)}


def verify(expected_count):
    """Verify that exactly expected_count transactions were recorded."""
    return len(_entries) == expected_count


def reset_ledger():
    """Clear all ledger entries."""
    _entries.clear()
