"""Feature flag system with env -> config -> hardcoded fallback chain.

Lookup order:
  1. Environment variable (via env.get_env_bool)
  2. Config file (via config.get_config_bool)
  3. Hardcoded defaults
"""

from env import get_env_bool
from config import get_config_bool

HARDCODED_DEFAULTS = {
    "dark_mode": False,
    "beta": False,
    "analytics": False,
}

# Maps flag names to their env var keys
_ENV_KEY_MAP = {
    "dark_mode": "FEATURE_DARK_MODE",  # FIX: correct underscore in env key
    "beta": "FEATURE_BETA",
    "analytics": "FEATURE_ANALYTICS",
}


def is_enabled(flag_name):
    """Check if a feature flag is enabled.

    Checks env first, then config, then hardcoded defaults.
    """
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
    """Return which layer provides the flag value (for debugging)."""
    env_key = _ENV_KEY_MAP.get(flag_name)
    if env_key:
        from env import get_env

        if get_env(env_key) is not None:
            return "env"

    from config import get_config

    if get_config(flag_name) is not None:
        return "config"

    return "hardcoded"
