"""Case 6 (B): Config derivation pipeline.

Chain: env_reader → config_parser → settings_deriver → service_initializer
Bypass: get_parsed_config reads config_parser output directly for config audit
Bug: config_parser reads PORT as string instead of int. Derived pool_size = PORT * 2 = "80808080..." (string repeat)
Canonical field: parsed config dict from config_parser
"""

from data.deep_dependency_chain.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system ──

ENV_VARS = {
    "primary": {"HOST": "prod.example.com", "PORT": "8080", "MAX_CONN": "50", "DEBUG": "false"},
    "alternate_port": {"HOST": "staging.example.com", "PORT": "3000", "MAX_CONN": "10", "DEBUG": "true"},
    "trap_catching_input": {"HOST": "dev.example.com", "PORT": "443", "MAX_CONN": "5", "DEBUG": "false"},
}


def _read_env(env_id):
    return dict(ENV_VARS[env_id])


def _parse_config_buggy(env):
    """BUG: PORT stays as string. All other numeric fields correctly converted."""
    return {
        "host": env["HOST"],
        "port": env["PORT"],  # BUG: should be int(env["PORT"])
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
    """Derives pool_size and listen_address from parsed config."""
    port = parsed_config.get("port_int", parsed_config["port"]) if use_port_int else parsed_config["port"]
    pool_size = port * 2  # int: 8080*2=16160. string: "8080"*2="80808080"
    listen_addr = f"{parsed_config['host']}:{port}"
    timeout = 30 if not parsed_config["debug"] else 5
    return {
        "pool_size": pool_size,
        "listen_address": listen_addr,
        "timeout": timeout,
        "max_conn": parsed_config["max_conn"],
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
    }


def _init_service(settings):
    """Initializes service from derived settings."""
    pool_size = settings["pool_size"]
    if isinstance(pool_size, str) or pool_size > 100000:
        return {"status": "error", "reason": f"invalid pool_size: {pool_size}",
                "settings": settings}
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
        pool_size = 16160  # hardcoded fallback
    elif pool_size > 20000:
        pool_size = 16160  # cap to expected value
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

    # Step A: parse config
    if patch_id == "root_fix":
        parsed = _parse_config_fixed(env)
    elif patch_id == "trap_5":
        parsed = _parse_config_trap5(env)
    else:
        parsed = _parse_config_buggy(env)

    # Bypass
    audit = _get_parsed_config(parsed)

    # Step B: derive settings
    if patch_id == "trap_3":
        settings = _derive_settings_with_cast(parsed)
    elif patch_id == "trap_5":
        settings = _derive_settings(parsed, use_port_int=True)
    elif patch_id == "trap_4":
        # Downstream override: deriver reads env directly to get port
        settings = _derive_settings(parsed)
        # Re-derive with correct port from env
        correct_port = int(env["PORT"])
        settings["pool_size"] = correct_port * 2
        settings["listen_address"] = f"{parsed['host']}:{correct_port}"
    else:
        settings = _derive_settings(parsed)

    # Step C: init service
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
    # PORT=8080 → pool_size should be 16160. Service should be "ok".
    res = r["result"]
    return res["status"] == "ok" and res["pool_size"] == 16160


def _run_invariant_trap_catching(patch_id):
    """PORT=443 → pool_size should be 886. Trap_1 caps anything > 20000 to 16160
    but 886 < 20000 → no cap → 886. Wait, with buggy config: PORT="443",
    pool_size = "443" * 2 = "443443" (string repeat). Trap_1: isinstance(str) →
    fallback to 16160. Expected: 886. 16160 ≠ 886 → FAIL."""
    r = _run_chain(patch_id, "trap_catching_input")
    res = r["result"]
    # PORT=443 → correct pool_size = 886
    expected = 886
    if res["status"] != "ok":
        return False, f"status={res['status']}", "port_443"
    passed = res["pool_size"] == expected
    return passed, f"pool_size={res['pool_size']}, expected={expected}", "port_443"


def _run_invariant_generalization(patch_id):
    """PORT=3000 → pool_size should be 6000.
    Trap_3 casts port to int in deriver → works for primary (8080).
    But also works for 3000. So generalization passes for trap_3.
    Need a case where trap_3 fails...

    Actually: trap_3 casts inside deriver. The LISTEN_ADDRESS also uses port.
    With buggy config: port="3000". listen_addr = "staging.example.com:3000" → correct as string.
    With trap_3: port cast to int → listen_addr = "staging.example.com:3000" → same.
    Hmm, trap_3 handles this correctly.

    The generalization failure for trap_3: the parsed config port is still a string.
    Other consumers of parsed_config (not deriver) will see string port.
    But my chain only has deriver as consumer...

    Let me check: does trap_3 fail any invariant?
    - causal_location: parsed["port"] is still string → FAIL
    - cross_path: audit port_type="str", service port_type from pool_size is int → FAIL
    - chain_integrity: parsed port (str) → settings pool_size (int) → inconsistent?
      Actually pool_size = int("8080") * 2 = 16160. And parsed port = "8080".
      int("8080") * 2 = 16160. parsed_port * 2 would be "80808080". They differ → FAIL.

    So trap_3 fails cross_path, chain_integrity, and causal_location.
    Cross_path has highest precedence → PRIMARY.

    Same issue as logging case — cross_path catches everything.
    But I specified trap_3 PRIMARY = generalization.

    Fix: trap_3 must modify parsed config (not just deriver). If trap_3 casts port
    to int in the parsed config dict before deriving, then:
    - parsed["port"] = int → causal_location PASSES
    - audit port_type = "int" → cross_path PASSES (if we check port_type)
    - chain_integrity: parsed port (int) matches settings pool_size derivation → PASSES

    But then what fails? The cast works for standard numeric ports but fails for
    non-numeric port values like PORT="auto" in an alternate env.
    """
    r = _run_chain(patch_id, "alternate_port")
    res = r["result"]
    # PORT=3000 → pool_size = 6000
    expected = 6000
    if res["status"] != "ok":
        return False, f"status={res['status']}", "port_3000"
    passed = res["pool_size"] == expected
    return passed, f"pool_size={res['pool_size']}, expected={expected}", "port_3000"


def _run_invariant_causal_location(patch_id):
    """Parsed config port must be int."""
    r = _run_chain(patch_id, "primary")
    port = r["parsed"]["port"]
    passed = isinstance(port, int) and port == 8080
    return passed, f"port={port!r} (type={type(port).__name__}), expected=int(8080)", None


def _run_invariant_cross_path(patch_id):
    """Audit (bypass) must report port as int.
    If parser leaves port as string, audit shows port_type=str while
    service uses int-derived pool_size → inconsistent."""
    r = _run_chain(patch_id, "primary")
    audit_type = r["audit"]["port_type"]
    # Service pool_size should be derived from int port
    service_ok = r["result"]["status"] == "ok" and isinstance(r["result"].get("pool_size"), int)
    # Consistency: if service treats port as int, audit should too
    consistent = audit_type == "int"
    return consistent, f"audit_port_type={audit_type}, service_ok={service_ok}", None


def _run_invariant_chain_integrity(patch_id):
    """Parsed port and derived pool_size must be mathematically consistent.
    pool_size should equal port * 2 where port comes from parsed config."""
    r = _run_chain(patch_id, "primary")
    parsed_port = r["parsed"]["port"]
    pool_size = r["settings"]["pool_size"]
    if isinstance(parsed_port, int):
        expected_pool = parsed_port * 2
    else:
        # String port → string multiplication → not a valid int
        expected_pool = None
    if expected_pool is None:
        # Can't verify consistency when port is string
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


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="config_derivation_chain",
        difficulty="B",
        domain="configuration management",
        scenario="Config parser reads PORT as string instead of int. "
                 "Downstream deriver computes pool_size = PORT * 2 which becomes "
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
            ChainNode("env_reader", "env.py", "read_env", "reads raw env vars as strings"),
            ChainNode("config_parser", "parser.py", "parse_config",
                      "parses env → typed config — BUG: port stays string"),
            ChainNode("settings_deriver", "deriver.py", "derive_settings",
                      "computes pool_size, listen_address from parsed config"),
            ChainNode("service_initializer", "service.py", "init_service",
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
                     "audit (bypass) still shows port_type=str; inconsistent with service treating port as int",
                     "cross_path", None),
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
