"""Role definitions and their access levels."""


def admin_access():
    """Full access for admins."""
    return {"read": True, "write": True, "delete": True}


def user_access():
    """Standard access for regular users."""
    return {"read": True, "write": True, "delete": False}


def moderator_access():
    """Moderators can read and delete but not write."""
    return {"read": True, "write": False, "delete": True}


def guest_access():
    """Guests get read-only access."""
    return {"read": True, "write": False, "delete": False}
