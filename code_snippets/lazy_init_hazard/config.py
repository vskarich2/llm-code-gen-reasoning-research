_settings = None


def get_settings():
    global _settings
    if _settings is None:
        _settings = _load_defaults()
    return _settings


def _load_defaults():
    return {"timeout": 30, "retries": 3, "debug": False}


def override_settings(overrides):
    s = get_settings()
    s.update(overrides)


def reset():
    global _settings
    _settings = None
