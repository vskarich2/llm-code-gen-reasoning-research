POLICIES = {
    "v1": {"version": "v1", "behavior": "legacy", "fallback": True},
    "v2": {"version": "v2", "behavior": "intermediate", "fallback": False},
    "v3": {"version": "v3", "behavior": "latest", "fallback": False},
}

def resolve_policy(request):
    if request.get("requires_legacy"):
        version = "v1"
    else:
        version = "v3"

    return {
        "resolved_version": version,
        "policy": POLICIES[version],
        "request_id": request.get("id"),
    }
