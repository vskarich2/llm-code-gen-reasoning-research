DEFAULT_CONTEXT = {"flags": {"force_fallback": False}}


def attach_compatibility_context(request, resolved_policy):
    context = DEFAULT_CONTEXT.copy()

    if request.get("requires_legacy"):
        context["flags"]["force_fallback"] = True

    request["compat"] = context
    return request
