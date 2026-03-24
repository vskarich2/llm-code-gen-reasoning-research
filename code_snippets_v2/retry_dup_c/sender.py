"""Message sender with retry logic."""

from store import append, notify

_attempt_count = 0


def reset_sender():
    global _attempt_count
    _attempt_count = 0


def send(msg, fail_first=False):
    """Send a message: store it and notify."""
    global _attempt_count
    _attempt_count += 1
    if fail_first and _attempt_count == 1:
        raise ConnectionError("transient failure")
    append(msg)
    notify(msg)
    return True


def send_with_retry(msg, max_retries=2, fail_first=False):
    """Retry send on transient errors."""
    for attempt in range(max_retries):
        try:
            send(msg, fail_first=fail_first)
            break
        except ConnectionError:
            continue
    return True


def get_attempt_count():
    return _attempt_count
