

_settings = {"host": "localhost", "port": 8080, "debug": False}

_default_host = _settings["host"]


def get_host():

    return _default_host


def get_settings():

    return dict(_settings)


def reset_settings():

    global _settings
    _settings = {"host": "localhost", "port": 8080, "debug": False}


def configure(host=None, port=None, debug=None):

    if host is not None:
        _settings["host"] = host
    if port is not None:
        _settings["port"] = port
    if debug is not None:
        _settings["debug"] = debug
