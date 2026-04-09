from middleware import ConfigMiddleware


def handle_request(overrides=None):
    mw = ConfigMiddleware()
    config = mw.apply_config(overrides)
    return {
        "timeout": config["timeout"],
        "retries": config["retries"],
        "debug": config["debug"],
    }


def handle_debug_request():
    return handle_request({"debug": True})
