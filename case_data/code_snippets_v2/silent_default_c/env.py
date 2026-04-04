"""Environment variable access layer."""

# Simulated environment variables (instead of os.environ)
_ENV = {
    "FEATURE_DARK_MODE": "true",
    "FEATURE_BETA": "false",
    "FEATURE_ANALYTICS": "true",
    "APP_DEBUG": "false",
}


def get_env(key, default=None):
    """Look up an environment variable.

    Args:
        key: the env var name to look up
        default: value to return if not found

    Returns:
        The string value, or default if not found.
    """
    return _ENV.get(key, default)


def get_env_bool(key, default=False):
    """Look up an env var and convert to bool.

    Recognizes "true"/"1"/"yes" as True (case-insensitive).
    """
    val = get_env(key)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")
