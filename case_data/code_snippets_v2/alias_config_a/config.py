DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}


def create_config(overrides=None):
    """Return a config dict based on defaults, with optional overrides."""
    config = DEFAULTS  # BUG: returns reference, not copy
    if overrides:
        config.update(overrides)
    return config


def reset_defaults():
    """Restore defaults to factory values."""
    global DEFAULTS
    DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
