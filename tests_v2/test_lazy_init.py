"""Tests for lazy_init family (execution_model_mismatch).

Invariant: after reset + reconfigure, all getters must reflect the new config.
"""


def test_a(mod):
    """Level A: get_host() must reflect config changes after configure()."""
    # Reset module state
    reset = getattr(mod, "reset_settings", None)
    configure = getattr(mod, "configure", None)
    get_host = getattr(mod, "get_host", None)
    if not all([reset, configure, get_host]):
        return False, ["missing reset_settings, configure, or get_host"]

    # Reset _settings to defaults
    _settings = getattr(mod, "_settings", None)
    if isinstance(_settings, dict):
        _settings.clear()
        _settings.update({"host": "localhost", "port": 8080, "debug": False})
    # Also reset the captured _default_host if it exists
    if hasattr(mod, "_default_host"):
        mod._default_host = "localhost"

    try:
        configure(host="prod.example.com")
        result = get_host()
    except Exception as e:
        return False, [f"raised: {e}"]

    if result != "prod.example.com":
        return False, [
            f"get_host() returned stale value: {result!r}, "
            f"expected 'prod.example.com'"
        ]

    return True, ["get_host() reflects configure() changes"]


def test_b(mod):
    """Level B: after reset_config + set_config, client must see new values."""
    reset = getattr(mod, "reset_config", None)
    set_config = getattr(mod, "set_config", None)
    get_timeout = getattr(mod, "get_timeout", None)
    if not all([reset, set_config, get_timeout]):
        return False, ["missing reset_config, set_config, or get_timeout"]

    # Reset any captured config
    if hasattr(mod, "_client_config"):
        mod._client_config = None
    if hasattr(mod, "_config"):
        mod._config = None

    try:
        reset()
        set_config("timeout", 99)
        result = get_timeout()
    except Exception as e:
        return False, [f"raised: {e}"]

    if result != 99:
        return False, [
            f"get_timeout() returned stale value: {result!r}, expected 99"
        ]

    return True, ["client reads config lazily after reset"]


def test_c(mod):
    """Level C: after reset_config + set_config, handler must see new values."""
    reset = getattr(mod, "reset_config", None)
    set_config = getattr(mod, "set_config", None)
    make_request = getattr(mod, "make_request", None)
    if not all([reset, set_config, make_request]):
        return False, ["missing reset_config, set_config, or make_request"]

    # Reset captured state
    if hasattr(mod, "_client_cfg"):
        mod._client_cfg = None
    if hasattr(mod, "_config"):
        mod._config = None

    try:
        reset()
        set_config("api_key", "new-secret-key")
        set_config("base_url", "https://new-api.example.com")
        result = make_request("users")
    except Exception as e:
        return False, [f"raised: {e}"]

    if result is None:
        return False, ["make_request returned None"]

    errors = []
    if result.get("api_key") != "new-secret-key":
        errors.append(
            f"api_key stale: {result.get('api_key')!r}, expected 'new-secret-key'"
        )
    if "new-api.example.com" not in result.get("url", ""):
        errors.append(
            f"base_url stale: url={result.get('url')!r}, "
            f"expected to contain 'new-api.example.com'"
        )

    if errors:
        return False, errors
    return True, ["handler reflects config changes through entire chain"]
