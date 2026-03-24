"""Role definitions with permission sets."""

ROLE_TYPES = {"admin", "user", "moderator", "service_account", "guest"}


def get_role_level(role):
    """Return numeric privilege level for a role."""
    levels = {
        "admin": 100,
        "service_account": 80,
        "moderator": 60,
        "user": 40,
        "guest": 10,
    }
    return levels.get(role, 0)


def is_valid_role(role):
    """Check if a role string is recognized."""
    return role in ROLE_TYPES
