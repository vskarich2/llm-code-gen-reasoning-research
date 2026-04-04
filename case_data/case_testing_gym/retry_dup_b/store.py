"""Message store with notification tracking."""

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
