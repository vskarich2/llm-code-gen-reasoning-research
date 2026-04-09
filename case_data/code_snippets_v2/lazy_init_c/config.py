_config = None


def _load_config():
    return {"api_key": "default-key", "base_url": "https://api.example.com"}


def get_config():
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def reset_config():
    global _config
    _config = None


def set_config(key, value):
    cfg = get_config()
    cfg[key] = value
