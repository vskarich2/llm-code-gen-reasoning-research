_config = {
    "max_connections": 10,
    "timeout_seconds": 30,
    "debug_mode": False,
    "log_level": "INFO",
}


def get_config():
    return _config


def reload(new_values):
    global _config
    # BUG: replaces the dict reference instead of mutating in-place.
    # Existing holders of the old reference see stale values.
    _config = dict(new_values)


def get_value(key, default=None):
    return _config.get(key, default)


def reset():
    global _config
    _config = {
        "max_connections": 10,
        "timeout_seconds": 30,
        "debug_mode": False,
        "log_level": "INFO",
    }
