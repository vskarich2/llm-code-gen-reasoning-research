"""Core rate limiter logic."""

from policy import is_expired, is_under_limit, is_exempt


def should_allow(client_id, count, limit, timestamp, now, window_seconds, exempt_list):
    """Decide whether to allow a request.

    Allow if:
      - token is not expired AND (under limit OR exempt)

    Exempt clients bypass the rate limit even if over it,
    but expired tokens are always rejected.
    """
    expired = is_expired(timestamp, now, window_seconds)
    under_limit = is_under_limit(count, limit)
    exempt = is_exempt(client_id, exempt_list)

    # FIX: explicit parentheses for correct precedence
    return not expired and (under_limit or exempt)
