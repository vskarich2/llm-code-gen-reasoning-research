_flags = {"new_pricing": False, "v2_api": False, "audit_mode": True}


def is_enabled(flag):
    return _flags.get(flag, False)


def enable(flag):
    _flags[flag] = True


def disable(flag):
    _flags[flag] = False


def get_all_flags():
    return dict(_flags)
