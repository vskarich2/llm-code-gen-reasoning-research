from defaults import get_base_config


def create_config(overrides=None, inherit=True):
    if inherit:
        base = get_base_config()
    else:
        base = {"timeout": 10, "retries": 1, "debug": False}
    if overrides:
        base.update(overrides)
    return base
