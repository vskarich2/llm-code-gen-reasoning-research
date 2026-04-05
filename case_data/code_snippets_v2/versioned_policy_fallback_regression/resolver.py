"""Resolver — determines which policy version applies to a request."""

from policy_loader import get_policy, get_latest_version, get_fallback_version


def resolve_policy(request):
    """Resolve the policy version for a request.

    If the request explicitly requires legacy, use fallback.
    Otherwise, use the latest version.
    """
    if request.get("requires_legacy"):
        version = get_fallback_version()
    else:
        version = get_latest_version()

    policy = get_policy(version)
    return {
        "resolved_version": version,
        "policy": policy,
        "request_id": request.get("id"),
    }
