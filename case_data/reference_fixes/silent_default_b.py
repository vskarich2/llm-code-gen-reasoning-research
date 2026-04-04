"""Feature flag access via dot-path traversal."""

from config import _CONFIG


def get_flag(path, default=False):
    """Traverse nested config using dot-separated path.

    Example: get_flag("feature.dark_mode") -> True

    Returns default if any key in the path is missing.
    """
    keys = path.split(".")
    current = _CONFIG
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def is_analytics_enabled():
    """Check if analytics is enabled.

    Should traverse: feature -> analytics -> enabled
    """
    # FIX: use "feature" (singular) not "features" (plural)
    return get_flag("feature.analytics.enabled")
