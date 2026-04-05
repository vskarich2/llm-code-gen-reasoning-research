"""Reference fix: fresh nested structure per request instead of shallow copy."""


def attach_compatibility_context(request, resolved_policy):
    # FIX: fresh nested structure per request
    context = {"flags": {"force_fallback": False}}

    if request.get("requires_legacy"):
        context["flags"]["force_fallback"] = True

    request["compat"] = context
    return request
