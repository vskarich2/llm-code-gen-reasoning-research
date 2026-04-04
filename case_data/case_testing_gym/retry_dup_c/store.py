"""Message store with deduplication support."""

_messages = []
_notifications = []


def reset():
    global _messages, _notifications
    _messages = []
    _notifications = []


def append(msg):
    """Store a message."""
    _messages.append(msg)


def notify(msg):
    """Record a notification for the message."""
    _notifications.append({"msg": msg, "notified": True})


def get_messages():
    return list(_messages)


def get_notifications():
    return list(_notifications)


def message_count():
    return len(_messages)


def deduplicate():
    """Remove duplicate messages. Useful for batch cleanup."""
    global _messages
    seen = set()
    unique = []
    for m in _messages:
        key = m if isinstance(m, str) else str(m)
        if key not in seen:
            seen.add(key)
            unique.append(m)
    _messages = unique
