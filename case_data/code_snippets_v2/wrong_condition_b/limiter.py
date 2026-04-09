from policy import is_allowed

class RateLimiter:

    def __init__(self, rate_limit=100, daily_quota=10000):
        self.rate_limit = rate_limit
        self.daily_quota = daily_quota
        self._minute_count = 0
        self._daily_count = 0

    def try_request(self):
        allowed = is_allowed(
            self._minute_count, self.rate_limit,
            self._daily_count, self.daily_quota,
        )
        if allowed:
            self._minute_count += 1
            self._daily_count += 1
        return allowed

    def reset_minute(self):
        self._minute_count = 0

    def get_stats(self):
        return {
            "minute": self._minute_count,
            "daily": self._daily_count,
        }
