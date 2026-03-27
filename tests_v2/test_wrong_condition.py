"""Tests for wrong_condition family (edge_case_omission).

Invariant: Rate limiting conditions must use correct operators.
           Off-by-one and logical operator errors silently allow excess.
"""


def test_a(mod):
    """Level A: > vs >= off-by-one in is_rate_limited."""
    is_rate_limited = getattr(mod, "is_rate_limited", None)
    if is_rate_limited is None:
        return False, ["is_rate_limited not found"]

    try:
        # With limit=5, count=5 means 5 requests already made.
        # Should be blocked (at the limit).
        result = is_rate_limited(5, 5)
    except Exception as e:
        return False, [f"is_rate_limited raised: {e}"]

    if not result:
        return False, [
            f"is_rate_limited(5, 5) returned False, expected True. "
            f"count==limit means limit reached, should block."
        ]

    return True, ["is_rate_limited correctly blocks at exact limit"]


def test_b(mod):
    """Level B: 'or' vs 'and' in policy check."""
    is_allowed = getattr(mod, "is_allowed", None)
    if is_allowed is None:
        return False, ["is_allowed not found"]

    try:
        # Rate OK (50 < 100) but quota exceeded (10001 >= 10000)
        # Should be blocked because BOTH must pass.
        result = is_allowed(
            requests_per_minute=50,
            rate_limit=100,
            daily_total=10001,
            daily_quota=10000,
        )
    except Exception as e:
        return False, [f"is_allowed raised: {e}"]

    if result:
        return False, [
            f"is_allowed(rpm=50, rate_limit=100, daily=10001, quota=10000) "
            f"returned True. Rate is OK but quota exceeded — should block."
        ]

    return True, ["is_allowed correctly requires both rate AND quota"]


def test_c(mod):
    """Level C: operator precedence bug in should_allow.

    Correct logic: not expired AND (under_limit OR exempt)
    Bug: ((not expired) AND under_limit) OR exempt
    Difference: when expired=True and exempt=True,
      buggy returns True (exempt alone is enough),
      correct returns False (expired always blocks).
    """
    should_allow = getattr(mod, "should_allow", None)
    if should_allow is None:
        return False, ["should_allow not found"]

    try:
        # Scenario: expired token + exempt client + over limit
        # expired=True (100-0 > 60), over limit (200 >= 100), exempt=True
        # Correct: not True and (False or True) = False and True = False
        # Buggy:   (not True and False) or True = (False and False) or True = True
        result = should_allow(
            client_id="internal-service",
            count=200,  # over limit
            limit=100,
            timestamp=0,  # long ago
            now=100,  # expired: (100-0) > 60
            window_seconds=60,
            exempt_list={"internal-service"},
        )
    except Exception as e:
        return False, [f"should_allow raised: {e}"]

    if result:
        return False, [
            f"should_allow returned True for expired token + exempt client. "
            f"Expected False: expired tokens must always be rejected, "
            f"even for exempt clients."
        ]

    return True, ["should_allow correctly blocks expired exempt clients"]
