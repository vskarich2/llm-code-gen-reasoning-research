"""Rate limiting policy definitions."""


def is_expired(timestamp, now, window_seconds):
    """Check if a timestamp is outside the current window."""
    return (now - timestamp) > window_seconds


def is_under_limit(count, limit):
    """Check if count is under the allowed limit."""
    return count < limit


def is_exempt(client_id, exempt_list):
    """Check if a client is exempt from rate limiting."""
    return client_id in exempt_list
