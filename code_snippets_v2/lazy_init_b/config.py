"""Configuration module with lazy loading."""

_config = None


def _load_config():
    """Load config (simulated)."""
    return {"db_url": "postgres://localhost/app", "timeout": 30}


def get_config():
    """Lazy-load and return config."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def reset_config():
    """Reset config so next get_config() reloads."""
    global _config
    _config = None


def set_config(key, value):
    """Override a config value."""
    cfg = get_config()
    cfg[key] = value
