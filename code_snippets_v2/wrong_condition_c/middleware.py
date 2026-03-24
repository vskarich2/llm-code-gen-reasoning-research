"""Rate limiting middleware for request processing."""

from limiter import should_allow


# Default configuration
DEFAULT_WINDOW = 60  # seconds
DEFAULT_LIMIT = 100
EXEMPT_CLIENTS = {"internal-service", "health-checker"}


def process_request(request, client_states):
    """Process a request through the rate limiter.

    Args:
        request: dict with 'client_id' and 'timestamp'
        client_states: dict mapping client_id -> {count, first_seen}

    Returns:
        dict with 'allowed' and 'reason'
    """
    client_id = request["client_id"]
    now = request["timestamp"]

    state = client_states.get(client_id, {"count": 0, "first_seen": now})

    allowed = should_allow(
        client_id=client_id,
        count=state["count"],
        limit=DEFAULT_LIMIT,
        timestamp=state["first_seen"],
        now=now,
        window_seconds=DEFAULT_WINDOW,
        exempt_list=EXEMPT_CLIENTS,
    )

    if allowed:
        state["count"] = state.get("count", 0) + 1
        client_states[client_id] = state
        return {"allowed": True, "reason": "ok"}

    return {"allowed": False, "reason": "rate_limited"}
