DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}

def create_config(overrides=None):
    config = DEFAULTS
    if overrides:
        config.update(overrides)
    return config

def merge_overrides(base, overrides):
    result = dict(base)
    result.update(overrides)
    return result


def get_default(key):
    return DEFAULTS.get(key)


def reset_defaults():
    global DEFAULTS
    DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
