"""Request middleware: validates role and attaches permissions."""

from roles import is_valid_role


def authenticate(request):
    """Validate the request and attach role-based context.

    Returns a context dict with 'role' and 'allowed' flag.
    Handles all known roles including service_account.
    """
    role = request.get("role", "guest")
    if not is_valid_role(role):
        return {"role": role, "allowed": False, "reason": "unknown_role"}

    # Middleware correctly recognizes service_account
    if role in ("admin", "service_account", "moderator"):
        return {"role": role, "allowed": True, "elevated": True}
    elif role in ("user", "guest"):
        return {"role": role, "allowed": True, "elevated": False}

    return {"role": role, "allowed": False, "reason": "unhandled"}
