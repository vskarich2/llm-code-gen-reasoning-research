

FLAGS = {
    "dark_mode": True,
    "beta_features": False,
    "new_dashboard": True,
    "analytics_v2": False,
}


def is_enabled(flag_name):
    """Check if a feature flag is enabled.

    Args:
        flag_name: the flag key to look up (must be snake_case)

    Returns:
        True if the flag is enabled, False otherwise.
    """
    return FLAGS.get(flag_name, False)


def list_flags():
    """Return all flag names."""
    return list(FLAGS.keys())
