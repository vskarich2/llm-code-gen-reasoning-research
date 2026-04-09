

from middleware import authenticate
from roles import get_role_level


def authorize(request):
    ctx = authenticate(request)
    if not ctx.get("allowed"):
        return {"can_read": False, "can_write": False, "can_admin": False}

    role = ctx["role"]

    if role == "admin":
        return {"can_read": True, "can_write": True, "can_admin": True}
    elif role == "moderator":
        return {"can_read": True, "can_write": False, "can_admin": True}
    elif role == "user":
        return {"can_read": True, "can_write": True, "can_admin": False}
    elif role == "guest":
        return {"can_read": True, "can_write": False, "can_admin": False}
    else:
        return {"can_read": False, "can_write": False, "can_admin": False}


def get_authorization_summary(request):
    result = authorize(request)
    perms = [k for k, v in result.items() if v]
    return {"role": request.get("role"), "permissions": perms}
