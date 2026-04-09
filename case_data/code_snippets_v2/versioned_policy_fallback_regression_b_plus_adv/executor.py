from normalizer import normalize_context


def execute_policy(request, resolved):
    norm = normalize_context(request)
    flags = norm.get("resolved_flags", {})
    version = resolved["resolved_version"]
    policy = resolved["policy"]

    if flags.get("force_fallback"):
        return {
            "request_id": request.get("id"),
            "executed_version": "v1",
            "behavior": "legacy",
            "source": "fallback_override",
        }

    return {
        "request_id": request.get("id"),
        "executed_version": version,
        "behavior": policy["behavior"],
        "source": "resolved",
    }
