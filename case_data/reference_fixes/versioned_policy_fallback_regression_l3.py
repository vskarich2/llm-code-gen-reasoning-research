"""Reference fix: compute fresh compat context per request, no shared state."""


def attach_compatibility_context(request, resolved_policy):
    compat = {"force_fallback": False}

    if request.get("requires_legacy"):
        compat["force_fallback"] = True

    request["compat"] = compat
    return request
