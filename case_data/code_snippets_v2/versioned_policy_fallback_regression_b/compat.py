BASE_CONTEXT = {"flags": {"force_fallback": False}}


def build_base_context():
    # BUG: shallow copy preserves nested aliasing
    return BASE_CONTEXT.copy()


def attach_compatibility_context(request, resolved_policy):
    context = build_base_context()

    if request.get("requires_legacy"):
        context["flags"]["force_fallback"] = True

    request["compat"] = context
    return request
