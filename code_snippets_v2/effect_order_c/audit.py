"""Audit log for compliance tracking."""

_audit_log = []


def reset():
    global _audit_log
    _audit_log = []


def audit_log(item_id, action, detail):
    """Record an audit entry for a specific item."""
    _audit_log.append({"item_id": item_id, "action": action, "detail": detail})


def get_audit_log():
    return list(_audit_log)


def audit_summary():
    """Return count of audit entries by action type."""
    summary = {}
    for entry in _audit_log:
        action = entry["action"]
        summary[action] = summary.get(action, 0) + 1
    return summary
