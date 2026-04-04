from config_loader import get_config

# Grab a reference at import time — will become stale after reload()
_cfg_ref = get_config()


def validate_connection_limit(requested):
    max_conn = _cfg_ref.get("max_connections", 10)
    if requested > max_conn:
        return False, f"requested {requested} exceeds max {max_conn}"
    return True, "ok"


def validate_timeout(value):
    max_timeout = _cfg_ref.get("timeout_seconds", 30)
    if value > max_timeout:
        return False, f"timeout {value} exceeds max {max_timeout}"
    return True, "ok"


def is_debug():
    return _cfg_ref.get("debug_mode", False)


def get_log_level():
    return _cfg_ref.get("log_level", "INFO")


def reset():
    global _cfg_ref
    _cfg_ref = get_config()
