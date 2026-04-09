def normalize_context(request):
    compat = request.get("compat", {})
    flags = compat.get("flags", {})
    return {
        "resolved_flags": flags,
        "execution_mode": compat.get("mode", "standard"),
    }
