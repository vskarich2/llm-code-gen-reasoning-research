"""Service with eagerly loaded settings."""

_settings = {"host": "localhost", "port": 8080, "debug": False}

# BUG: _default_host captured eagerly from _settings at import time
_default_host = _settings["host"]


def get_host():
    """Return the current host setting."""
    return _default_host


def get_settings():
    """Return the current settings dict."""
    return dict(_settings)


def reset_settings():
    """Reset settings to new values (e.g., for testing)."""
    global _settings
    _settings = {"host": "localhost", "port": 8080, "debug": False}


def configure(host=None, port=None, debug=None):
    """Update settings."""
    if host is not None:
        _settings["host"] = host
    if port is not None:
        _settings["port"] = port
    if debug is not None:
        _settings["debug"] = debug
