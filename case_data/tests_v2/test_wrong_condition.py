"""Tests for wrong_condition family (edge_case_omission).

Invariant: Rate limiting conditions must use correct operators.
           Both allow AND deny outcomes must be tested.

Equivalence policy: behavior_only
Mechanism evidence: NONE
Strength: STRONG (V2.1 — was WEAK, added complements + anti-hardcoding)

V2.1: `return True` and `return False` now correctly FAIL.
"""


def test_a(mod):
    """Level A: > vs >= off-by-one in is_rate_limited."""
    is_rate_limited = getattr(mod, "is_rate_limited", None)
    if is_rate_limited is None:
        return False, ["is_rate_limited not found"]

    errors = []
    try:
        # DENY: at limit — must block
        if not is_rate_limited(5, 5):
            errors.append("is_rate_limited(5, 5)=False, expected True (at limit)")

        # COMPLEMENT: below limit — must allow
        if is_rate_limited(4, 5):
            errors.append("is_rate_limited(4, 5)=True, expected False (under limit)")

        # DENY: over limit — must block
        if not is_rate_limited(6, 5):
            errors.append("is_rate_limited(6, 5)=False, expected True (over limit)")

        # ANTI-HARDCODING: zero requests with different limit
        if is_rate_limited(0, 3):
            errors.append("is_rate_limited(0, 3)=True, expected False (no requests)")

        # ANTI-HARDCODING: at-limit with different limit value
        if not is_rate_limited(3, 3):
            errors.append("is_rate_limited(3, 3)=False, expected True (at limit=3)")

    except Exception as e:
        return False, [f"is_rate_limited raised: {e}"]

    if errors:
        return False, errors
    return True, ["blocks at/above limit, allows below, multiple limits"]


def test_b(mod):
    """Level B: 'or' vs 'and' in policy check."""
    is_allowed = getattr(mod, "is_allowed", None)
    if is_allowed is None:
        return False, ["is_allowed not found"]

    errors = []
    try:
        # DENY: rate OK but quota exceeded
        if is_allowed(requests_per_minute=50, rate_limit=100,
                      daily_total=10001, daily_quota=10000):
            errors.append("quota exceeded but allowed (should block)")

        # COMPLEMENT: both within limits — must allow
        if not is_allowed(requests_per_minute=50, rate_limit=100,
                          daily_total=5000, daily_quota=10000):
            errors.append("both OK but blocked (should allow)")

        # DENY: rate exceeded but quota OK
        if is_allowed(requests_per_minute=150, rate_limit=100,
                      daily_total=5000, daily_quota=10000):
            errors.append("rate exceeded but allowed (should block)")

        # ANTI-HARDCODING: minimal valid request
        if not is_allowed(requests_per_minute=0, rate_limit=1,
                          daily_total=0, daily_quota=1):
            errors.append("minimal valid request blocked (should allow)")

    except Exception as e:
        return False, [f"is_allowed raised: {e}"]

    if errors:
        return False, errors
    return True, ["requires both rate AND quota, tests allow+deny"]


def test_c(mod):
    """Level C: operator precedence in should_allow."""
    should_allow = getattr(mod, "should_allow", None)
    if should_allow is None:
        return False, ["should_allow not found"]

    errors = []
    try:
        # DENY: expired + exempt — must block (expired overrides exempt)
        if should_allow(client_id="internal-service", count=200, limit=100,
                        timestamp=0, now=100, window_seconds=60,
                        exempt_list={"internal-service"}):
            errors.append("expired+exempt allowed (should block)")

        # COMPLEMENT: valid + under limit + non-exempt — allow
        if not should_allow(client_id="user-1", count=50, limit=100,
                            timestamp=95, now=100, window_seconds=60,
                            exempt_list=set()):
            errors.append("valid under-limit request blocked (should allow)")

        # COMPLEMENT: valid + over limit + exempt — allow
        if not should_allow(client_id="health-checker", count=200, limit=100,
                            timestamp=95, now=100, window_seconds=60,
                            exempt_list={"health-checker"}):
            errors.append("valid exempt client blocked (should allow)")

        # ANTI-HARDCODING: different window, different client
        if not should_allow(client_id="user-42", count=10, limit=50,
                            timestamp=98, now=100, window_seconds=60,
                            exempt_list=set()):
            errors.append("normal valid request blocked (should allow)")

    except Exception as e:
        return False, [f"should_allow raised: {e}"]

    if errors:
        return False, errors
    return True, ["precedence correct, both allow+deny tested"]
