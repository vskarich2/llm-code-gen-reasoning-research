"""Tests for config_derivation_chain.

Bug: config_parser leaves PORT as string. pool_size = PORT * 2 = string repetition.
Fix: int(env["PORT"]) in parse_config.
"""


def test(mod):
    errors = []

    read_env_node = getattr(mod, "read_env_node", None)
    parse_config = getattr(mod, "parse_config", None)
    derive_settings_node = getattr(mod, "derive_settings_node", None)
    init_service_node = getattr(mod, "init_service_node", None)
    if not read_env_node or not parse_config or not derive_settings_node or not init_service_node:
        return False, ["required functions not found: read_env_node, parse_config, derive_settings_node, init_service_node"]

    RAW_DATA = getattr(mod, "RAW_DATA", None)
    if RAW_DATA is None:
        return False, ["RAW_DATA not found in module"]

    # Invariant 1: PORT=8080 -> pool_size=16160, status=ok
    env = read_env_node(RAW_DATA["primary"])
    parsed = parse_config(env)
    if not isinstance(parsed["port"], int):
        errors.append(f"invariant 1: port={parsed['port']!r} (type {type(parsed['port']).__name__}), expected int")
    settings = derive_settings_node(parsed)
    result = init_service_node(settings)
    if result["status"] != "ok":
        errors.append(f"invariant 1: status={result['status']!r}, reason={result.get('reason')!r}")
    elif result["pool_size"] != 16160:
        errors.append(f"invariant 1: pool_size={result['pool_size']}, expected 16160")

    # Invariant 2: PORT=443 -> pool_size=886 (not hardcoded fallback)
    env443 = read_env_node(RAW_DATA["trap_catching"])
    parsed443 = parse_config(env443)
    settings443 = derive_settings_node(parsed443)
    result443 = init_service_node(settings443)
    if result443["status"] != "ok":
        errors.append(f"invariant 2: PORT=443 status={result443['status']!r}")
    elif result443["pool_size"] != 886:
        errors.append(f"invariant 2: PORT=443 pool_size={result443['pool_size']}, expected 886")

    # Invariant 3: PORT=3000 -> pool_size=6000
    env3000 = read_env_node(RAW_DATA["alt_port"])
    parsed3000 = parse_config(env3000)
    settings3000 = derive_settings_node(parsed3000)
    result3000 = init_service_node(settings3000)
    if result3000["status"] != "ok":
        errors.append(f"invariant 3: PORT=3000 status={result3000['status']!r}")
    elif result3000["pool_size"] != 6000:
        errors.append(f"invariant 3: PORT=3000 pool_size={result3000['pool_size']}, expected 6000")

    return not errors, errors
