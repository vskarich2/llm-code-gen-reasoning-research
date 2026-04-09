
from roles import is_valid_role


def authenticate(request):
    role = request.get("role", "guest")
    if not is_valid_role(role):
        return {"role": role, "allowed": False, "reason": "unknown_role"}

    if role in ("admin", "service_account", "moderator"):
        return {"role": role, "allowed": True, "elevated": True}
    elif role in ("user", "guest"):
        return {"role": role, "allowed": True, "elevated": False}

    return {"role": role, "allowed": False, "reason": "unhandled"}
