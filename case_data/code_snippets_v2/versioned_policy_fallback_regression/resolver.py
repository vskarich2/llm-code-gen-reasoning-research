from policy_loader import get_policy, get_latest_version, get_fallback_version


def resolve_policy(request):
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
