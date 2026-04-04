_log = []


def handle_standard(event):
    _log.append(("standard", event["id"]))
    return {
        "status": "processed",
        "handler": "standard",
        "timeout": 30,
        "escalated": False,
        "event_id": event["id"],
    }


def handle_priority(event):
    _log.append(("priority", event["id"]))
    return {
        "status": "processed",
        "handler": "priority",
        "timeout": 5,
        "escalated": True,
        "event_id": event["id"],
    }


def handle_batch(event):
    _log.append(("batch", event["id"]))
    return {
        "status": "queued",
        "handler": "batch",
        "timeout": 120,
        "escalated": False,
        "event_id": event["id"],
    }


def get_log():
    return list(_log)


def reset():
    _log.clear()
