"""Core rate limiter logic."""

from policy import is_expired, is_under_limit, is_exempt


def should_allow(client_id, count, limit, timestamp, now,
                 window_seconds, exempt_list):
    """Decide whether to allow a request.

    Allow if:
      - token is not expired AND (under limit OR exempt)

    Exempt clients bypass the rate limit even if over it,
    but expired tokens are always rejected.
    """
    expired = is_expired(timestamp, now, window_seconds)
    under_limit = is_under_limit(count, limit)
    exempt = is_exempt(client_id, exempt_list)

    # BUG: operator precedence — Python parses this as:
    #   ((not expired) and under_limit) or exempt
    # Correct intent: (not expired) and (under_limit or exempt)
    # When expired=True AND exempt=True:
    #   buggy:  (False and under_limit) or True = True  (allows!)
    #   correct: False and (under_limit or True) = False (blocks!)
    return not expired and under_limit or exempt
