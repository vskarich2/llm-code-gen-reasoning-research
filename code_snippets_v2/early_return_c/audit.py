"""Audit log for charge operations."""

_log = []


def log_charge(txn_id, amount, source="direct"):
    """Record a charge event for audit purposes."""
    _log.append({
        "txn_id": txn_id,
        "amount": amount,
        "source": source,
    })


def verify_completeness(expected_count):
    """Verify that exactly expected_count charges were logged."""
    return len(_log) == expected_count


def get_log():
    """Return a copy of the audit log."""
    return list(_log)


def reset_audit():
    """Clear all audit log entries."""
    _log.clear()
