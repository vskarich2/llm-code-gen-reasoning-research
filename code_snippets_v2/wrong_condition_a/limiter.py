"""Simple rate limiter."""


def is_rate_limited(count, limit):
    """Check if the request count has reached the rate limit.

    Args:
        count: current number of requests made
        limit: maximum allowed requests

    Returns:
        True if the caller should be blocked, False if allowed.
    """
    # BUG: uses > instead of >=. Allows exactly limit requests
    # when it should allow limit-1 (0-indexed count starts at 0,
    # so count==limit means limit+1 requests have been made).
    return count > limit


def check_and_increment(current_count, limit):
    """Check rate limit and return (blocked, new_count).

    If not blocked, increments the count.
    """
    if is_rate_limited(current_count, limit):
        return True, current_count
    return False, current_count + 1
