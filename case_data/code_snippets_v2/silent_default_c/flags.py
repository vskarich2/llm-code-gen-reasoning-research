
from env import get_env_bool
from config import get_config_bool


HARDCODED_DEFAULTS = {
    "dark_mode": False,
    "beta": False,
    "analytics": False,
}


_ENV_KEY_MAP = {
    "dark_mode": "FEATURE_DARKMODE",
    "beta": "FEATURE_BETA",
    "analytics": "FEATURE_ANALYTICS",
}


def is_enabled(flag_name):
    env_key = _ENV_KEY_MAP.get(flag_name)
    if env_key:
        env_val = get_env_bool(env_key)
        if env_val:
            return True

    config_val = get_config_bool(flag_name)
    if config_val is not None:
        return config_val

    return HARDCODED_DEFAULTS.get(flag_name, False)


def get_flag_source(flag_name):
    env_key = _ENV_KEY_MAP.get(flag_name)
    if env_key:
        from env import get_env
        if get_env(env_key) is not None:
            return "env"

    from config import get_config
    if get_config(flag_name) is not None:
        return "config"

    return "hardcoded"
