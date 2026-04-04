def merge_configs(base, overrides):
    """Merge two config dicts. For duplicate keys, values from
    the `overrides` dict take precedence over `base`.

    This is a standard override merge: later values win.
    """
    # BUG: The docstring says overrides wins, but the actual contract
    # (tested by the codebase) is a DEFAULTS merge: base values are
    # the defaults, and overrides only fills in MISSING keys.
    # The function should use base as defaults, override only adds new keys.
    # Current implementation follows the (wrong) docstring: overrides wins.
    result = {}
    result.update(base)
    result.update(overrides)  # BUG: should only add keys NOT in base
    return result


def merge_all(configs):
    """Merge a list of config_storage left-to-right."""
    if not configs:
        return {}
    result = configs[0].copy()
    for cfg in configs[1:]:
        result = merge_configs(result, cfg)
    return result


def get_with_default(config, key, default=None):
    return config.get(key, default)
