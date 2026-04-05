"""Compatibility handler — attaches compatibility context to requests."""

_COMPAT = {}


def get_compat():
    return _COMPAT


def attach_compatibility_context(request, resolved_policy):
    compat = get_compat()

    if request.get("requires_legacy"):
        compat["force_fallback"] = True

    request["compat"] = compat
    return request
