"""Rate and quota policy checks."""


def check_rate(requests_per_minute, rate_limit):
    """Return True if rate is within acceptable bounds."""
    return requests_per_minute < rate_limit


def check_quota(daily_total, daily_quota):
    """Return True if daily quota is not exceeded."""
    return daily_total < daily_quota


def is_allowed(requests_per_minute, rate_limit, daily_total, daily_quota):
    """Check if a request is allowed under BOTH rate and quota policies.

    A request should only be allowed if it passes rate AND quota checks.
    """
    rate_ok = check_rate(requests_per_minute, rate_limit)
    quota_ok = check_quota(daily_total, daily_quota)
    # FIX: uses 'and' — requires BOTH conditions to pass
    return rate_ok and quota_ok
