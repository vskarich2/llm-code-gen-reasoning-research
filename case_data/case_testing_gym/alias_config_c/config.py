DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}


def create_config(overrides=None):
    """Return a config dict based on defaults, with optional overrides."""
    config = DEFAULTS  # BUG: returns reference, not copy
    if overrides:
        config.update(overrides)
    return config


def merge_overrides(base, overrides):
    """Merge overrides into a copy of base. Used by admin tools.
    NOTE: This function correctly copies — tempting to route through it,
    but it changes the call semantics for middleware.
    """
    result = dict(base)
    result.update(overrides)
    return result


def get_default(key):
    """Read a single default value."""
    return DEFAULTS.get(key)


def reset_defaults():
    """Restore defaults to factory values."""
    global DEFAULTS
    DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
