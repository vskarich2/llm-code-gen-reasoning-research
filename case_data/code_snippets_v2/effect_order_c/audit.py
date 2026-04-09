
_audit_log = []


def reset():
    global _audit_log
    _audit_log = []


def audit_log(item_id, action, detail):
    _audit_log.append({"item_id": item_id, "action": action, "detail": detail})


def get_audit_log():
    return list(_audit_log)


def audit_summary():
    summary = {}
    for entry in _audit_log:
        action = entry["action"]
        summary[action] = summary.get(action, 0) + 1
    return summary
