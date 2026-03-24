"""Configuration layer — reads from file-like config store."""

_FILE_CONFIG = {
    "dark_mode": True,
    "beta": False,
    "analytics": True,
}


def get_config(key, default=None):
    """Read a config value from the file-based config store."""
    return _FILE_CONFIG.get(key, default)


def get_config_bool(key, default=False):
    """Read a config value and return as bool."""
    val = get_config(key)
    if val is None:
        return default
    return bool(val)
