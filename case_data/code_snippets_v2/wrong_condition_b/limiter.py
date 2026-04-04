"""Rate limiter using policy checks."""

from policy import is_allowed


class RateLimiter:
    """Tracks request counts and enforces rate + quota policies."""

    def __init__(self, rate_limit=100, daily_quota=10000):
        self.rate_limit = rate_limit
        self.daily_quota = daily_quota
        self._minute_count = 0
        self._daily_count = 0

    def try_request(self):
        """Attempt a request. Returns True if allowed, False if blocked."""
        allowed = is_allowed(
            self._minute_count, self.rate_limit,
            self._daily_count, self.daily_quota,
        )
        if allowed:
            self._minute_count += 1
            self._daily_count += 1
        return allowed

    def reset_minute(self):
        """Reset the per-minute counter (called each minute)."""
        self._minute_count = 0

    def get_stats(self):
        """Return current counters."""
        return {
            "minute": self._minute_count,
            "daily": self._daily_count,
        }
