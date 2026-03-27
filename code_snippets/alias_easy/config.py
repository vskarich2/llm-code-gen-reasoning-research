DEFAULTS = {"timeout": 30, "retries": 3}


def create_config(overrides=None):
    config = DEFAULTS  # BUG: alias, not copy
    if overrides:
        config.update(overrides)
    return config
