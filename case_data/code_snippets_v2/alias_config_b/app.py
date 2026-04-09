from config import create_config

_cached_settings = None


def get_settings():

    global _cached_settings
    if _cached_settings is None:
        _cached_settings = create_config()
    return _cached_settings


def apply_overrides(overrides):

    settings = get_settings()
    settings.update(overrides)
    return settings


def clear_cache():

    global _cached_settings
    _cached_settings = None
