DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}


def create_config(overrides=None):
    config = DEFAULTS
    if overrides:
        config.update(overrides)
    return config


def reset_defaults():

    global DEFAULTS
    DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
