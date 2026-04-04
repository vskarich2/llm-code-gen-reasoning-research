from middleware import ConfigMiddleware


def handle_request(overrides=None):
    """Process a request using middleware config."""
    mw = ConfigMiddleware()
    config = mw.apply_config(overrides)
    return {
        "timeout": config["timeout"],
        "retries": config["retries"],
        "debug": config["debug"],
    }


def handle_debug_request():
    """Handle a debug request that enables debug mode."""
    return handle_request({"debug": True})
