"""Feature flag system with snake_case keys."""

FLAGS = {
    "dark_mode": True,
    "beta_features": False,
    "new_dashboard": True,
    "analytics_v2": False,
}


def _normalize_key(flag_name):
    """Convert camelCase to snake_case for consistent lookup."""
    import re
    # Insert underscore before uppercase letters and lowercase them
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", flag_name)
    return s1.lower()


def is_enabled(flag_name):
    """Check if a feature flag is enabled.

    Args:
        flag_name: the flag key (accepts camelCase or snake_case)

    Returns:
        True if the flag is enabled, False otherwise.
    """
    # FIX: normalize key to snake_case before lookup
    key = _normalize_key(flag_name)
    return FLAGS.get(key, False)


def list_flags():
    """Return all flag names."""
    return list(FLAGS.keys())
