"""Nested configuration store."""

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
    """Return the raw config dict (for inspection)."""
    return _CONFIG


def validate_config():
    """Validate top-level config keys. Does NOT recurse."""
    required = {"feature", "ui"}
    return required.issubset(_CONFIG.keys())
