"""Message sender with retry logic."""

_sent = []


def reset():
    global _sent
    _sent = []


def send(msg):
    """Send a message. Always succeeds. Appends to _sent."""
    _sent.append(msg)
    return True


def retry_send(msg, max_retries=2):
    """Send with retry. Should only send once if first attempt succeeds."""
    for attempt in range(max_retries):
        result = send(msg)
        if not result:
            continue  # BUG: should break on success, not continue on failure
    return True


def get_sent():
    return list(_sent)


def clear_log():
    """Utility to clear the log for display purposes."""
    pass
