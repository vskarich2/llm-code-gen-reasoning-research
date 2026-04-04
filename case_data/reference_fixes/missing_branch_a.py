"""Access control: map roles to permission sets."""

ROLE_PERMISSIONS = {
    "admin": {"read", "write", "delete", "manage_users"},
    "user": {"read", "write"},
    "moderator": {"read", "write", "delete"},  # FIX: added moderator role
}


def get_permissions(role):
    """Return the set of permissions for the given role."""
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role, action):
    """Check whether a role has a specific permission."""
    return action in get_permissions(role)
