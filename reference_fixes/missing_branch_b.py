"""Authentication and authorization dispatch."""

from roles import admin_access, user_access, moderator_access, guest_access


# Dispatch table mapping roles to access handlers
_ROLE_DISPATCH = {
    "admin": admin_access,
    "user": user_access,
    "moderator": moderator_access,
    "guest": guest_access,  # FIX: added guest to dispatch table
}


def _default_access():
    """Default: no access for unknown roles."""
    return {"read": False, "write": False, "delete": False}


def get_access(role):
    """Return the access dict for a given role."""
    handler = _ROLE_DISPATCH.get(role, _default_access)
    return handler()


def can_read(role):
    """Check if role has read access."""
    return get_access(role).get("read", False)
