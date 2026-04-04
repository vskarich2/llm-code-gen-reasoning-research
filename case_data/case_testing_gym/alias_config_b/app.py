from config import create_config

_cached_settings = None


def get_settings():
    """Return app settings, caching the result."""
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = create_config()
    return _cached_settings


def apply_overrides(overrides):
    """Apply runtime overrides to the cached settings."""
    settings = get_settings()
    settings.update(overrides)
    return settings


def clear_cache():
    """Clear cached settings so next get_settings() re-reads defaults."""
    global _cached_settings
    _cached_settings = None
