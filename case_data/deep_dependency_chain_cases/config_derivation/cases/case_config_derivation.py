"""Case 6 (B): Config derivation pipeline.

Chain: env_reader → config_parser → settings_deriver → service_initializer
Bypass: get_parsed_config reads config_parser output directly for config audit
Bug: config_parser reads PORT as string instead of int. Derived pool_size = PORT * 2 = "80808080..." (string repeat)
Canonical field: parsed config dict from config_parser
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

ENV_VARS = {
    "primary": {"HOST": "prod.example.com", "PORT": "8080", "MAX_CONN": "50", "DEBUG": "false"},
    "alt_port": {"HOST": "staging.example.com", "PORT": "3000", "MAX_CONN": "10", "DEBUG": "true"},
    "trap_catching": {"HOST": "dev.example.com", "PORT": "443", "MAX_CONN": "5", "DEBUG": "false"},
}

RAW_DATA = {
    "primary": {"HOST": "prod.example.com", "PORT": "8080", "MAX_CONN": "50", "DEBUG": "false"},
    "alt_port": {"HOST": "staging.example.com", "PORT": "3000", "MAX_CONN": "10", "DEBUG": "true"},
    "trap_catching": {"HOST": "dev.example.com", "PORT": "443", "MAX_CONN": "5", "DEBUG": "false"},
}

CASE_DATA_GLOBALS = ["RAW_DATA"]


def _read_env(env_id):
    return dict(ENV_VARS[env_id])


def _parse_config_buggy(env):
    """BUG: PORT stays as string."""
    return {
        "host": env["HOST"],
        "port": env["PORT"],          # BUG: should be int(env["PORT"])
        "max_conn": int(env["MAX_CONN"]),
        "debug": env["DEBUG"].lower() == "true",
    }


def _parse_config_fixed(env):
    """ROOT FIX: convert PORT to int."""
    return {
        "host": env["HOST"],
        "port": int(env["PORT"]),
        "max_conn": int(env["MAX_CONN"]),
        "debug": env["DEBUG"].lower() == "true",
    }


def _parse_config_trap5(env):
    """TRAP 5: adds port_int alongside string port."""
    result = _parse_config_buggy(env)
    result["port_int"] = int(env["PORT"])
    return result


def _derive_settings(parsed_config, *, use_port_int=False):
    port = parsed_config.get("port_int", parsed_config["port"]) if use_port_int else parsed_config["port"]
    pool_size = port * 2
    listen_addr = f"{parsed_config['host']}:{port}"
    timeout = 30 if not parsed_config["debug"] else 5
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed_config["max_conn"],
        "port": port,
    }


def _derive_settings_with_cast(parsed_config):
    """TRAP 3: casts port to int inside deriver before math."""
    port = int(parsed_config["port"]) if isinstance(parsed_config["port"], str) else parsed_config["port"]
    pool_size = port * 2
    listen_addr = f"{parsed_config['host']}:{port}"
    timeout = 30 if not parsed_config["debug"] else 5
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed_config["max_conn"],
        "port": port,
    }


def _init_service(settings):
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str) or pool_size > 100000:
        return {"status": "error", "reason": f"invalid pool_size: {pool_size}",
                "pool_size": pool_size, "listen_address": settings["listen_address"]}
    return {
        "status": "ok",
        "pool_size": pool_size,
        "listen_address": settings["listen_address"],
        "timeout": settings["timeout"],
    }


def _init_service_capped(settings):
    """TRAP 1: caps pool_size at 20000 if it seems wrong."""
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str):
        pool_size = 16160
    elif pool_size > 20000:
        pool_size = 16160
    return {
        "status": "ok",
        "pool_size": pool_size,
        "listen_address": settings["listen_address"],
        "timeout": settings["timeout"],
        "capped": True,
    }


def _get_parsed_config(parsed_config):
    """BYPASS CONSUMER: reads parsed config directly for audit/compliance."""
    return {
        "port": parsed_config["port"],
        "port_type": type(parsed_config["port"]).__name__,
        "max_conn": parsed_config["max_conn"],
        "host": parsed_config["host"],
    }


# ── Dispatch ──

def _run_chain(patch_id, env_id="primary"):
    env = _read_env(env_id)

    if patch_id == "root_fix":
        parsed = _parse_config_fixed(env)
    elif patch_id == "trap_5":
        parsed = _parse_config_trap5(env)
    else:
        parsed = _parse_config_buggy(env)

    audit = _get_parsed_config(parsed)

    if patch_id == "trap_3":
        settings = _derive_settings_with_cast(parsed)
    elif patch_id == "trap_5":
        settings = _derive_settings(parsed, use_port_int=True)
    elif patch_id == "trap_4":
        settings = _derive_settings(parsed)
        correct_port = int(env["PORT"])
        settings["pool_size"] = correct_port * 2
        settings["listen_address"] = f"{parsed['host']}:{correct_port}"
    else:
        settings = _derive_settings(parsed)

    if patch_id == "trap_1":
        result = _init_service_capped(settings)
    else:
        result = _init_service(settings)

    return {
        "result": result,
        "audit": audit,
        "parsed": parsed,
        "settings": settings,
    }


# ── Test hooks ──

def _run_primary_test(patch_id):
    r = _run_chain(patch_id, "primary")
    res = r["result"]
    return res["status"] == "ok" and res["pool_size"] == 16160


def _run_invariant_trap_catching(patch_id):
    r = _run_chain(patch_id, "trap_catching")
    res = r["result"]
    expected = 886
    if res["status"] != "ok":
        return False, f"status={res['status']}", "port_443"
    passed = res["pool_size"] == expected
    return passed, f"pool_size={res['pool_size']}, expected={expected}", "port_443"


def _run_invariant_generalization(patch_id):
    r = _run_chain(patch_id, "alt_port")
    res = r["result"]
    expected = 6000
    if res["status"] != "ok":
        return False, f"status={res['status']}", "port_3000"
    passed = res["pool_size"] == expected
    return passed, f"pool_size={res['pool_size']}, expected={expected}", "port_3000"


def _run_invariant_causal_location(patch_id):
    r = _run_chain(patch_id, "primary")
    port = r["parsed"]["port"]
    passed = isinstance(port, int) and port == 8080
    return passed, f"port={port!r} (type={type(port).__name__}), expected=int(8080)", None


def _run_invariant_cross_path(patch_id):
    r = _run_chain(patch_id, "primary")
    audit_type = r["audit"]["port_type"]
    consistent = audit_type == "int"
    return consistent, f"audit_port_type={audit_type}", None


def _run_invariant_chain_integrity(patch_id):
    r = _run_chain(patch_id, "primary")
    parsed_port = r["parsed"]["port"]
    pool_size = r["settings"]["pool_size"]
    if isinstance(parsed_port, int):
        expected_pool = parsed_port * 2
    else:
        expected_pool = None
    if expected_pool is None:
        return False, f"parsed_port={parsed_port!r} is string, can't verify chain", None
    consistent = pool_size == expected_pool
    return consistent, f"parsed_port={parsed_port}, pool_size={pool_size}, expected={expected_pool}", None


def _classify_depth(patch_id):
    if patch_id == "root_fix":
        return "A"
    if patch_id == "trap_1":
        return "D"
    if patch_id == "trap_3":
        return "C"
    if patch_id == "trap_4":
        return "B"
    if patch_id == "trap_5":
        return "B"
    return "unrelated"


# ── Compiler-compatible node functions ──

# @node: env_reader
# @role: main
def _read_env_node(env):
    return dict(env)


# @node: config_parser
# @role: buggy
def _parse_config(env):
    return {
        "host": env["HOST"],
        "port": env["PORT"],          # BUG: should be int(env["PORT"])
        "max_conn": int(env["MAX_CONN"]),
        "debug": env["DEBUG"].lower() == "true",
    }


# @node: settings_deriver
# @role: main
def _derive_settings_node(parsed):
    port = parsed["port"]
    pool_size = port * 2
    listen_addr = f"{parsed['host']}:{port}"
    timeout = 5 if parsed["debug"] else 30
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed["max_conn"],
        "port": port,
    }


# @node: service_initializer
# @role: main
def _init_service_node(settings):
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str) or (isinstance(pool_size, int) and pool_size > 500000):
        return {"status": "error", "reason": f"invalid pool_size: {pool_size!r}",
                "pool_size": pool_size, "listen_address": settings["listen_address"]}
    return {
        "status": "ok",
        "pool_size": pool_size,
        "listen_address": settings["listen_address"],
        "timeout": settings["timeout"],
    }


# @node: service_initializer
# @role: trap_1
def _init_service_capped_node(settings):
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str):
        pool_size = 16160
    elif pool_size > 20000:
        pool_size = 16160
    return {
        "status": "ok",
        "pool_size": pool_size,
        "listen_address": settings["listen_address"],
        "timeout": settings["timeout"],
    }


# @node: settings_deriver
# @role: trap_3
def _derive_settings_cast_node(parsed):
    port = int(parsed["port"]) if isinstance(parsed["port"], str) else parsed["port"]
    pool_size = port * 2
    listen_addr = f"{parsed['host']}:{port}"
    timeout = 5 if parsed["debug"] else 30
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed["max_conn"],
        "port": port,
    }


# @node: settings_deriver
# @role: trap_4
def _derive_settings_reread_node(parsed):
    port = int(parsed["port"]) if isinstance(parsed["port"], str) else parsed["port"]
    pool_size = port * 2
    listen_addr = f"{parsed['host']}:{port}"
    timeout = 5 if parsed["debug"] else 30
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed["max_conn"],
        "port": port,
    }


# @node: config_parser
# @role: trap_5
def _parse_config_trap5_node(env):
    return {
        "host": env["HOST"],
        "port": env["PORT"],
        "port_int": int(env["PORT"]),
        "max_conn": int(env["MAX_CONN"]),
        "debug": env["DEBUG"].lower() == "true",
    }


# @node: settings_deriver
# @role: trap_5
def _derive_settings_trap5_node(parsed):
    port = parsed.get("port_int", parsed["port"])
    pool_size = port * 2
    listen_addr = f"{parsed['host']}:{port}"
    timeout = 5 if parsed["debug"] else 30
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed["max_conn"],
        "port": port,
    }


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="config_derivation_chain",
        difficulty="B",
        domain="configuration management",
        scenario="Config parser reads PORT env var as string instead of int. "
                 "Settings deriver computes pool_size = PORT * 2 which becomes "
                 "string repetition instead of integer multiplication.",
        nodes=NodeDeclarations(
            source_of_truth_node="env_reader",
            corruption_introduced_at_node="config_parser",
            first_observable_symptom_node="settings_deriver",
            required_fix_node="config_parser",
        ),
        canonical=CanonicalRepresentation(
            field_names=["port"],
            schema_description="int, the TCP port number",
            storage_location="parsed config dict from config_parser",
            access_paths=[
                "settings_deriver reads port for pool_size calculation",
                "settings_deriver reads port for listen_address",
                "get_parsed_config reads port directly (BYPASS for audit)",
            ],
        ),
        chain=[
            ChainNode("env_reader", "env.py", "read_env_node", "reads raw env vars as strings"),
            ChainNode("config_parser", "parser.py", "parse_config",
                      "parses env → typed config — BUG: port stays string"),
            ChainNode("settings_deriver", "deriver.py", "derive_settings_node",
                      "computes pool_size, listen_address from parsed config"),
            ChainNode("service_initializer", "service.py", "init_service_node",
                      "initializes service from derived settings"),
        ],
        bypass_consumer="get_parsed_config",
        bypass_description="reads port directly from parsed config for audit; "
                           "no deriver/service calls; no shared logic",
        bug_description="config_parser does not int() the PORT env var. "
                        "port stays as string '8080'. pool_size = '8080' * 2 = '80808080' (string repeat).",
        root_fix_description="add int() conversion for PORT in config_parser",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "service_initializer caps/fallbacks pool_size when it looks wrong",
                     "if pool_size is string or > 20000: use hardcoded 16160",
                     "directly fixes the service startup for primary port",
                     "audit (bypass) still shows port_type=str; PORT=443 gives wrong fallback",
                     "trap_catching", None),
            TrapSpec("trap_3", "validation_masking", "C",
                     "settings_deriver casts port to int before math",
                     "port = int(parsed['port']) if isinstance(str) else parsed['port']",
                     "produces correct pool_size and listen_address",
                     "parsed config port is still string; cross_path detects audit shows str type",
                     "cross_path", None),
            TrapSpec("trap_4", "downstream_override", "B",
                     "settings_deriver reads PORT directly from env vars",
                     "re-read env to get correct int port, bypass parsed config",
                     "produces correct derived settings",
                     "audit (bypass) still reads string port from parsed config",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "config_parser adds port_int field alongside string port",
                     "parsed['port_int'] = int(PORT); parsed['port'] still string",
                     "correct int value available; deriver uses port_int",
                     "audit reads port (not port_int) → reports string type",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "PORT=443 → pool_size must be 886 (not hardcoded fallback)",
                          [{"desc": "port 443 pool_size check"}]),
            InvariantSpec("generalization",
                          "PORT=3000 → pool_size must be 6000",
                          [{"desc": "alternate port 3000"}]),
            InvariantSpec("causal_location",
                          "parsed config port must be int(8080), not string '8080'",
                          [{"desc": "port type check"}]),
            InvariantSpec("cross_path",
                          "audit must report port_type=int (consistent with service's int usage)",
                          [{"desc": "audit port_type consistency"}]),
            InvariantSpec("chain_integrity",
                          "parsed port × 2 must equal derived pool_size (mathematical consistency)",
                          [{"desc": "port-poolsize consistency"}]),
        ],
    )

    spec.run_primary_test = _run_primary_test
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching,
        "generalization": _run_invariant_generalization,
        "causal_location": _run_invariant_causal_location,
        "cross_path": _run_invariant_cross_path,
        "chain_integrity": _run_invariant_chain_integrity,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
