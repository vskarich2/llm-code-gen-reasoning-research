from config_loader import reload as reload_config, get_config
from validator import validate_connection_limit, validate_timeout


def apply_new_config(new_values):
    reload_config(new_values)
    return {"status": "reloaded", "config": dict(get_config())}


def request_connections(n):
    ok, msg = validate_connection_limit(n)
    if not ok:
        raise ValueError(msg)
    return f"allocated {n} connections"


def request_with_timeout(timeout_value):
    ok, msg = validate_timeout(timeout_value)
    if not ok:
        raise ValueError(msg)
    return f"timeout set to {timeout_value}"


def reconfigure_and_validate(new_values, test_connections, test_timeout):
    apply_new_config(new_values)
    conn_result = request_connections(test_connections)
    timeout_result = request_with_timeout(test_timeout)
    return {
        "connections": conn_result,
        "timeout": timeout_result,
    }
