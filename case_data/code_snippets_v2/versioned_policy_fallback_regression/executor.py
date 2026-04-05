"""Executor — executes policy behavior based on resolved context."""


def execute_policy(request, resolved):
    """Execute the policy for a request.

    Uses compatibility context to determine if fallback behavior
    should override the resolved version.
    """
    compat = request.get("compat", {})
    policy = resolved["policy"]
    version = resolved["resolved_version"]

    if compat.get("force_fallback"):
        return {
            "request_id": request.get("id"),
            "executed_version": "v1",
            "behavior": "legacy",
            "source": "fallback_override",
        }

    return {
        "request_id": request.get("id"),
        "executed_version": version,
        "behavior": policy["behavior"],
        "source": "resolved",
    }
