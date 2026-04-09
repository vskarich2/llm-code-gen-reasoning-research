POLICIES = {
    "v1": {"version": "v1", "behavior": "legacy", "fallback": True},
    "v3": {"version": "v3", "behavior": "latest", "fallback": False},
}

_BASE_COMPAT = {"flags": {"force_fallback": False}, "mode": "standard"}


def resolve_policy(request):
    version = "v1" if request.get("requires_legacy") else "v3"
    return {
        "resolved_version": version,
        "policy": POLICIES[version],
        "request_id": request.get("id"),
    }


def attach_compatibility_context(request, resolved_policy):
    context = _BASE_COMPAT.copy()
    if request.get("requires_legacy"):
        context["flags"]["force_fallback"] = True
    request["compat"] = context
    return request
