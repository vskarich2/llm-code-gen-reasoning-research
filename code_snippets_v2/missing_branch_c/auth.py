"""Authorization handler: decides what a role can do."""

from middleware import authenticate
from roles import get_role_level


def authorize(request):
    """Authorize a request by checking middleware + handler logic.

    Returns dict with 'can_read', 'can_write', 'can_admin'.
    """
    ctx = authenticate(request)
    if not ctx.get("allowed"):
        return {"can_read": False, "can_write": False, "can_admin": False}

    role = ctx["role"]

    # BUG: handler doesn't handle "service_account" — falls to default
    if role == "admin":
        return {"can_read": True, "can_write": True, "can_admin": True}
    elif role == "moderator":
        return {"can_read": True, "can_write": False, "can_admin": True}
    elif role == "user":
        return {"can_read": True, "can_write": True, "can_admin": False}
    elif role == "guest":
        return {"can_read": True, "can_write": False, "can_admin": False}
    else:
        # Unknown role — no access
        return {"can_read": False, "can_write": False, "can_admin": False}


def get_authorization_summary(request):
    """Return a human-readable summary of authorization."""
    result = authorize(request)
    perms = [k for k, v in result.items() if v]
    return {"role": request.get("role"), "permissions": perms}
