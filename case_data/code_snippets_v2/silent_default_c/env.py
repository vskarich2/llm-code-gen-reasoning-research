_ENV = {
    "FEATURE_DARK_MODE": "true",
    "FEATURE_BETA": "false",
    "FEATURE_ANALYTICS": "true",
    "APP_DEBUG": "false",
}

def get_env(key, default=None):
    return _ENV.get(key, default)


def get_env_bool(key, default=False):
    val = get_env(key)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes")
