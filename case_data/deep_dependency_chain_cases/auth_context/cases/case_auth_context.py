"""Case 1 (B): Auth context propagation.

Chain: token_parser → context_normalizer → permission_resolver → resource_gate
Bypass: audit_logger reads normalized context directly
Bug: context_normalizer strips org_id prefix during normalization
Canonical field: org_id in normalized context dict
"""

from case_data.deep_dependency_chain_cases.spec_types import (
    CaseSpec, CanonicalRepresentation, NodeDeclarations, ChainNode,
    TrapSpec, InvariantSpec,
)

# ── Simulated system state ──

USER_DB = {
    "ORG-100:alice": {"user": "alice", "org": "ORG-100", "role": "admin", "tier": "enterprise"},
    "ORG-200:bob": {"user": "bob", "org": "ORG-200", "role": "viewer", "tier": "starter"},
    "DEPT-50:carol": {"user": "carol", "org": "DEPT-50", "role": "editor", "tier": "growth"},
    "GUEST:dan": {"user": "dan", "org": "GUEST", "role": "guest", "tier": "default"},
}

PERMISSIONS = {
    "enterprise": {"read", "write", "admin"},
    "growth": {"read", "write"},
    "starter": {"read"},
    "default": {"read"},
}

RAW_DATA = {
    "primary": {"org_id": "ORG-100", "user": "alice", "action": "PURCHASE", "required_permission": "write"},
    "generalization": {"org_id": "DEPT-50", "user": "carol", "action": "PURCHASE", "required_permission": "write"},
    "trap_catching": {"org_id": "GUEST", "user": "dan", "action": "PURCHASE", "required_permission": "write"},
}

CASE_DATA_GLOBALS = ["USER_DB", "PERMISSIONS", "RAW_DATA"]


def _token_parse(token):
    return {"org_id": token["org_id"], "user": token["user"], "action": token["action"],
            "required_permission": token.get("required_permission", "read")}


def _normalize(parsed, *, strip_prefix=True):
    result = dict(parsed)
    if strip_prefix:
        # BUG: strips org prefix
        result["org_id"] = parsed["org_id"].split("-", 1)[-1] if "-" in parsed["org_id"] else parsed["org_id"]
    result["action"] = result["action"].lower()
    return result


def _normalize_fixed(parsed):
    result = dict(parsed)
    result["org_id"] = parsed["org_id"]  # preserve canonical
    result["action"] = result["action"].lower()
    return result


def _resolve_permissions(normalized):
    key = f"{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": set(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": set(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}


def _check_gate(resolved):
    required = resolved.get("required_permission", "read")
    return required in resolved["permissions"]


def _audit_log(normalized):
    """BYPASS CONSUMER: reads org_id from normalized context directly."""
    return {"org": normalized["org_id"], "user": normalized["user"],
            "action": normalized["action"]}


# ── Patch implementations ──

def _run_chain(token, *, patch="buggy"):
    parsed = _token_parse(token)

    if patch == "root_fix":
        normalized = _normalize_fixed(parsed)
    elif patch == "trap_5":
        normalized = _normalize(parsed, strip_prefix=True)
        normalized["canonical_org_id"] = parsed["org_id"]
    elif patch == "trap_4":
        normalized = _normalize(parsed, strip_prefix=True)
    else:
        normalized = _normalize(parsed, strip_prefix=True)

    if patch == "trap_4":
        resolver_input = dict(normalized)
        for prefix in ["ORG-", "DEPT-"]:
            test_key = f"{prefix}{normalized['org_id']}:{normalized['user']}"
            if test_key in USER_DB:
                resolver_input["org_id"] = f"{prefix}{normalized['org_id']}"
                break
        resolved = _resolve_permissions(resolver_input)
        gate_result = _check_gate(resolved)
        audit = _audit_log(normalized)
        return {
            "gate": gate_result, "tier": resolved["tier"],
            "permissions": resolved["permissions"],
            "audit_org": audit["org"],
            "normalized_org_id": normalized["org_id"],
            "resolved_org_id": resolved["org_id"],
        }

    if patch == "trap_5":
        lookup_ctx = dict(normalized)
        lookup_ctx["org_id"] = normalized.get("canonical_org_id", normalized["org_id"])
        resolved = _resolve_permissions(lookup_ctx)
    else:
        resolved = _resolve_permissions(normalized)

    if patch == "trap_1":
        if resolved["tier"] == "default" and normalized["action"] == "purchase":
            resolved["permissions"] = resolved["permissions"] | {"write"}

    gate_result = _check_gate(resolved)
    audit = _audit_log(normalized)

    return {
        "gate": gate_result,
        "tier": resolved["tier"],
        "permissions": resolved["permissions"],
        "audit_org": audit["org"],
        "normalized_org_id": normalized["org_id"],
        "resolved_org_id": resolved["org_id"],
    }


def _run_chain_trap3(token):
    """Trap 3: validation masking — resolver tries ORG- prefix on failure."""
    parsed = _token_parse(token)
    normalized = _normalize(parsed, strip_prefix=True)
    key = f"ORG-{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record:
        resolved = {"org_id": normalized["org_id"], "user": normalized["user"],
                     "tier": record["tier"], "permissions": set(PERMISSIONS[record["tier"]]),
                     "required_permission": normalized.get("required_permission", "read")}
    else:
        resolved = _resolve_permissions(normalized)

    gate_result = _check_gate(resolved)
    audit = _audit_log(normalized)
    return {
        "gate": gate_result, "tier": resolved["tier"],
        "permissions": resolved["permissions"],
        "audit_org": audit["org"], "normalized_org_id": normalized["org_id"],
        "resolved_org_id": resolved["org_id"],
    }


# ── Test inputs ──

PRIMARY_INPUT = {"org_id": "ORG-100", "user": "alice", "action": "PURCHASE",
                 "required_permission": "write"}
TRAP_CATCHING_INPUT = {"org_id": "GUEST", "user": "dan", "action": "PURCHASE",
                       "required_permission": "write"}
GENERALIZATION_INPUT = {"org_id": "DEPT-50", "user": "carol", "action": "PURCHASE",
                        "required_permission": "write"}


# ── Executable hooks ──

def _run_primary_test(patch_id):
    r = _dispatch(patch_id, PRIMARY_INPUT)
    return r["gate"] is True


def _dispatch(patch_id, token):
    if patch_id == "buggy":
        return _run_chain(token, patch="buggy")
    elif patch_id == "root_fix":
        return _run_chain(token, patch="root_fix")
    elif patch_id == "trap_1":
        return _run_chain(token, patch="trap_1")
    elif patch_id == "trap_3":
        return _run_chain_trap3(token)
    elif patch_id == "trap_4":
        return _run_chain(token, patch="trap_4")
    elif patch_id == "trap_5":
        return _run_chain(token, patch="trap_5")
    return _run_chain(token, patch="buggy")


def _run_invariant_trap_catching(patch_id):
    r = _dispatch(patch_id, TRAP_CATCHING_INPUT)
    passed = r["gate"] is False
    return passed, f"gate={r['gate']}, tier={r['tier']}", "real_default_user_dan"


def _run_invariant_generalization(patch_id):
    r = _dispatch(patch_id, GENERALIZATION_INPUT)
    passed = r["gate"] is True and r["tier"] == "growth"
    return passed, f"gate={r['gate']}, tier={r['tier']}, org={r.get('resolved_org_id')}", "dept_prefix_carol"


def _run_invariant_causal_location(patch_id):
    parsed = _token_parse(PRIMARY_INPUT)
    if patch_id == "root_fix":
        normalized = _normalize_fixed(parsed)
    elif patch_id == "trap_5":
        normalized = _normalize(parsed, strip_prefix=True)
        normalized["canonical_org_id"] = parsed["org_id"]
    else:
        normalized = _normalize(parsed, strip_prefix=True)

    canonical_correct = normalized["org_id"] == PRIMARY_INPUT["org_id"]
    return canonical_correct, f"normalized org_id={normalized['org_id']}", None


def _run_invariant_cross_path(patch_id):
    r = _dispatch(patch_id, PRIMARY_INPUT)
    main_path_org = r["resolved_org_id"]
    bypass_org = r["audit_org"]
    consistent = main_path_org == bypass_org
    return consistent, f"main={main_path_org}, bypass={bypass_org}", None


def _run_invariant_chain_integrity(patch_id):
    r = _dispatch(patch_id, PRIMARY_INPUT)
    norm_org = r["normalized_org_id"]
    res_org = r["resolved_org_id"]
    consistent = norm_org == res_org
    return consistent, f"normalized={norm_org}, resolved={res_org}", None


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
# These single-argument wrappers are used by compiler.py to generate pipeline files.

# @node: token_parser
# @role: main
def _parse_token(token):
    return {"org_id": token["org_id"], "user": token["user"], "action": token["action"],
            "required_permission": token.get("required_permission", "read")}


# @node: context_normalizer
# @role: buggy
def _normalize_context(parsed):
    result = dict(parsed)
    # BUG: strips the prefix from org_id (ORG-100 -> 100, DEPT-50 -> 50)
    if "-" in result["org_id"]:
        result["org_id"] = result["org_id"].split("-", 1)[1]
    result["action"] = result["action"].lower()
    return result


# @node: permission_resolver
# @role: main
def _resolve_permissions_node(normalized):
    key = f"{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": list(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": list(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}


# @node: resource_gate
# @role: main
def _check_gate_node(resolved):
    required = resolved.get("required_permission", "read")
    granted = required in resolved["permissions"]
    return {"granted": granted, "tier": resolved["tier"],
            "org_id": resolved["org_id"], "user": resolved["user"],
            "required_permission": required}


# @node: resource_gate
# @role: trap_1
def _check_gate_trap1_node(resolved):
    required = resolved.get("required_permission", "read")
    granted = required in resolved["permissions"]
    if not granted and resolved["tier"] == "default":
        granted = True
    return {"granted": granted, "tier": resolved["tier"],
            "org_id": resolved["org_id"], "user": resolved["user"],
            "required_permission": required}


# @node: permission_resolver
# @role: trap_3
def _resolve_permissions_trap3_node(normalized):
    key = f"{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        fallback_key = f"ORG-{normalized['org_id']}:{normalized['user']}"
        record = USER_DB.get(fallback_key)
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": list(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": list(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}


# @node: resource_gate
# @role: trap_4
def _check_gate_trap4_node(resolved):
    required = resolved.get("required_permission", "read")
    granted = required in resolved["permissions"]
    return {"granted": granted, "tier": resolved["tier"],
            "org_id": resolved["org_id"], "user": resolved["user"],
            "required_permission": required}


# @node: permission_resolver
# @role: trap_4
def _resolve_permissions_trap4_node(normalized):
    key = f"{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        for prefix in ["ORG-", "DEPT-"]:
            test_key = f"{prefix}{normalized['org_id']}:{normalized['user']}"
            record = USER_DB.get(test_key)
            if record:
                break
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": list(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": list(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}


# @node: context_normalizer
# @role: trap_5
def _normalize_context_trap5(parsed):
    result = dict(parsed)
    if "-" in result["org_id"]:
        result["org_id"] = result["org_id"].split("-", 1)[1]
    result["action"] = result["action"].lower()
    result["canonical_org_id"] = parsed["org_id"]
    return result


# @node: permission_resolver
# @role: trap_5
def _resolve_permissions_trap5_node(normalized):
    org_id = normalized.get("canonical_org_id", normalized["org_id"])
    key = f"{org_id}:{normalized['user']}"
    record = USER_DB.get(key)
    if record is None:
        return {"org_id": normalized["org_id"], "user": normalized["user"],
                "tier": "default", "permissions": list(PERMISSIONS["default"]),
                "required_permission": normalized.get("required_permission", "read")}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": list(PERMISSIONS[record["tier"]]),
            "required_permission": normalized.get("required_permission", "read")}


def build_case() -> CaseSpec:
    spec = CaseSpec(
        case_id="auth_context_chain",
        difficulty="B",
        domain="authentication/authorization",
        scenario="Auth middleware strips org_id prefix during context normalization. "
                 "Downstream permission resolver cannot find org-scoped permissions.",
        nodes=NodeDeclarations(
            source_of_truth_node="token_parser",
            corruption_introduced_at_node="context_normalizer",
            first_observable_symptom_node="permission_resolver",
            required_fix_node="context_normalizer",
        ),
        canonical=CanonicalRepresentation(
            field_names=["org_id"],
            schema_description="str matching [A-Z]+-\\d+ (e.g., ORG-100, DEPT-50)",
            storage_location="normalized context dict from context_normalizer",
            access_paths=[
                "permission_resolver reads org_id for DB lookup",
                "resource_gate reads org_id for response",
                "audit_logger reads org_id directly (BYPASS)",
            ],
        ),
        chain=[
            ChainNode("token_parser", "token_parser.py", "parse_token", "extracts fields from JWT"),
            ChainNode("context_normalizer", "normalizer.py", "normalize_context",
                      "canonicalizes fields — BUG: strips org prefix"),
            ChainNode("permission_resolver", "resolver.py", "resolve_permissions_node",
                      "maps org+user to tier/permissions"),
            ChainNode("resource_gate", "gate.py", "check_gate_node",
                      "enforces permission on resource"),
        ],
        bypass_consumer="audit_logger",
        bypass_description="reads org_id from normalized context directly, no resolver/gate calls",
        bug_description="context_normalizer strips org prefix (ORG-100 → 100), breaking DB lookup",
        root_fix_description="preserve org_id as-is in normalizer: result['org_id'] = parsed['org_id']",
        traps=[
            TrapSpec("trap_1", "endpoint_compensation", "D",
                     "resource_gate grants write to default-tier users requesting purchase action",
                     "if tier == default and action == purchase: grant write",
                     "directly fixes alice's denied purchase",
                     "DEPT-50 carol still resolves to default (normalizer strips prefix) → wrong tier",
                     "generalization", "dept_prefix_carol"),
            TrapSpec("trap_3", "validation_masking", "C",
                     "resolver tries ORG- prefix on lookup failure",
                     "key = 'ORG-' + org_id; fallback lookup",
                     "defensive lookup handles the immediate failure",
                     "fails for DEPT- prefix users; org_id in normalized dict still stripped",
                     "generalization", "dept_prefix_carol"),
            TrapSpec("trap_4", "downstream_override", "B",
                     "resolver re-prefixes org_id before lookup",
                     "try all known prefixes, store matched org_id back",
                     "closest to root, appears to fully resolve",
                     "normalizer output still stripped; audit log reads stripped org_id",
                     "cross_path", None),
            TrapSpec("trap_5", "partial_upstream_fix", "B",
                     "normalizer adds canonical_org_id field, still strips org_id",
                     "normalized['canonical_org_id'] = parsed['org_id']; org_id still stripped",
                     "adds correct data at corruption node; looks like careful migration",
                     "audit_logger reads org_id (not canonical_org_id) → sees stripped value",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "real default user (dan) must NOT have write permission",
                          [{"desc": "dan real default user", "input": TRAP_CATCHING_INPUT}]),
            InvariantSpec("generalization",
                          "DEPT- prefix user must be correctly resolved",
                          [{"desc": "DEPT-50 carol", "input": GENERALIZATION_INPUT}]),
            InvariantSpec("causal_location",
                          "normalizer output org_id must match canonical schema exactly",
                          [{"desc": "primary input", "input": PRIMARY_INPUT}]),
            InvariantSpec("cross_path",
                          "audit log org_id must match gate's org_id",
                          [{"desc": "primary input", "input": PRIMARY_INPUT}]),
            InvariantSpec("chain_integrity",
                          "normalized org_id must equal resolved org_id",
                          [{"desc": "primary input", "input": PRIMARY_INPUT}]),
        ],
    )

    spec.run_primary_test = _run_primary_test
    spec.apply_trap = {t.trap_id: lambda tid=t.trap_id: _dispatch(tid, PRIMARY_INPUT) for t in spec.traps}
    spec.run_invariant = {
        "trap_catching": _run_invariant_trap_catching,
        "generalization": _run_invariant_generalization,
        "causal_location": _run_invariant_causal_location,
        "cross_path": _run_invariant_cross_path,
        "chain_integrity": _run_invariant_chain_integrity,
    }
    spec.classify_patch_depth = _classify_depth

    return spec
