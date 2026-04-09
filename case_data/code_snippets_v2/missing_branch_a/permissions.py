
ROLE_PERMISSIONS = {
    "admin": {"read", "write", "delete", "manage_users"},
    "user": {"read", "write"},
}

def get_permissions(role):
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(role, action):
    return action in get_permissions(role)
