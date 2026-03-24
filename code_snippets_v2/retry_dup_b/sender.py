"""Message sender with retry and store integration."""

from store import append, notify, get_messages, get_notifications

_attempt_count = 0


def reset():
    global _attempt_count, _messages, _notifications
    _attempt_count = 0
    _messages = []
    _notifications = []


def send(msg, fail_first=False):
    """Send a message: store it and notify.

    If fail_first is True, raises on first call to simulate transient error.
    """
    global _attempt_count
    _attempt_count += 1
    if fail_first and _attempt_count == 1:
        raise ConnectionError("transient failure")
    append(msg)
    notify(msg)
    return True


def send_with_retry(msg, max_retries=2, fail_first=False):
    """Retry send on transient errors."""
    last_error = None
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            # BUG: no break after success — continues loop, duplicating
        except ConnectionError as e:
            last_error = e
            continue
    return True


def get_attempt_count():
    return _attempt_count
