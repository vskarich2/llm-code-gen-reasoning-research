from config import _CONFIG

def get_flag(path, default=False):
    keys = path.split(".")
    current = _CONFIG
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current

def is_analytics_enabled():
    return get_flag("features.analytics.enabled")
