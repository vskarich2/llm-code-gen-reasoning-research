DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}


def create_config(overrides=None):
    """Return a config dict based on defaults, with optional overrides."""
    config = DEFAULTS.copy()  # FIX: copy prevents mutation of global
    if overrides:
        config.update(overrides)
    return config


def merge_overrides(base, overrides):
    """Merge overrides into a copy of base. Used by admin tools."""
    result = dict(base)
    result.update(overrides)
    return result


def reset_defaults():
    """Restore defaults to factory values."""
    global DEFAULTS
    DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
