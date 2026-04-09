_FILE_CONFIG = {
    "dark_mode": True,
    "beta": False,
    "analytics": True,
}

def get_config(key, default=None):
    return _FILE_CONFIG.get(key, default)

def get_config_bool(key, default=False):

    val = get_config(key)
    if val is None:
        return default
    return bool(val)
