"""Reference fix: fully independent nested structure in build_base_context."""


def build_base_context():
    # FIX: fully independent nested structure
    return {"flags": {"force_fallback": False}}


def attach_compatibility_context(request, resolved_policy):
    context = build_base_context()

    if request.get("requires_legacy"):
        context["flags"]["force_fallback"] = True

    request["compat"] = context
    return request
