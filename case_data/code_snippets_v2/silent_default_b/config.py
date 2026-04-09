_CONFIG = {
    "feature": {
        "dark_mode": True,
        "beta": False,
        "analytics": {"enabled": True, "version": 2},
    },
    "ui": {
        "theme": "light",
        "sidebar": True,
    },
}

def get_raw():
    return _CONFIG


def validate_config():
    required = {"feature", "ui"}
    return required.issubset(_CONFIG.keys())
