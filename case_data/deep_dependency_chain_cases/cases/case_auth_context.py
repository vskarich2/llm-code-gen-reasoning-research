"""Case 1 (B): Auth context propagation.

Chain: token_parser → context_normalizer → permission_resolver → resource_gate
Bypass: audit_logger reads normalized context directly
Bug: context_normalizer strips org_id prefix during normalization
Canonical field: org_id in normalized context dict
"""

from data.deep_dependency_chain.spec_types import (
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


def _token_parse(token):
    return {"org_id": token["org_id"], "user": token["user"], "action": token["action"]}


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
                "tier": "default", "permissions": PERMISSIONS["default"]}
    return {"org_id": normalized["org_id"], "user": normalized["user"],
            "tier": record["tier"], "permissions": PERMISSIONS[record["tier"]]}


def _check_gate(resolved, required_permission):
    return required_permission in resolved["permissions"]


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
        normalized["canonical_org_id"] = parsed["org_id"]  # alternate field
    elif patch == "trap_4":
        normalized = _normalize(parsed, strip_prefix=True)
        # downstream override: resolver re-prefixes
        # (normalizer untouched)
    else:
        normalized = _normalize(parsed, strip_prefix=True)

    if patch == "trap_4":
        # Downstream override: resolver gets a corrected COPY for lookup only
        # normalizer output (normalized dict) is NOT mutated
        resolver_input = dict(normalized)
        for prefix in ["ORG-", "DEPT-"]:
            test_key = f"{prefix}{normalized['org_id']}:{normalized['user']}"
            if test_key in USER_DB:
                resolver_input["org_id"] = f"{prefix}{normalized['org_id']}"
                break
        resolved = _resolve_permissions(resolver_input)
        gate_result = _check_gate(resolved, token.get("required_permission", "write"))
        audit = _audit_log(normalized)  # reads ORIGINAL normalized (still stripped)
        return {
            "gate": gate_result, "tier": resolved["tier"],
            "permissions": resolved["permissions"],
            "audit_org": audit["org"],
            "normalized_org_id": normalized["org_id"],  # still stripped
            "resolved_org_id": resolved["org_id"],  # re-prefixed
        }

    if patch == "trap_5":
        # resolver uses canonical_org_id for lookup
        lookup_ctx = dict(normalized)
        lookup_ctx["org_id"] = normalized.get("canonical_org_id", normalized["org_id"])
        resolved = _resolve_permissions(lookup_ctx)
    else:
        resolved = _resolve_permissions(normalized)

    if patch == "trap_1":
        # Endpoint compensation: grant write to default-tier users on purchase action
        if resolved["tier"] == "default" and normalized["action"] == "purchase":
            resolved["permissions"] = resolved["permissions"] | {"write"}

    gate_result = _check_gate(resolved, token.get("required_permission", "write"))

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
    # Try prefixed lookup
    key = f"ORG-{normalized['org_id']}:{normalized['user']}"
    record = USER_DB.get(key)
    if record:
        resolved = {"org_id": normalized["org_id"], "user": normalized["user"],
                     "tier": record["tier"], "permissions": PERMISSIONS[record["tier"]]}
    else:
        resolved = _resolve_permissions(normalized)

    gate_result = _check_gate(resolved, token.get("required_permission", "write"))
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
# Dan is a REAL default-tier user (GUEST:dan in DB). Normalizer stripping doesn't matter
# because his org "GUEST" has no dash prefix to strip. He is correctly resolved as default.
# Trap_1 grants write to default+purchase → dan gets write → WRONG.
TRAP_CATCHING_INPUT = {"org_id": "GUEST", "user": "dan", "action": "PURCHASE",
                       "required_permission": "write"}
GENERALIZATION_INPUT = {"org_id": "DEPT-50", "user": "carol", "action": "PURCHASE",
                        "required_permission": "write"}


# ── Executable hooks ──

def _run_primary_test(patch_id):
    r = _dispatch(patch_id, PRIMARY_INPUT)
    # alice should have write permission (observable symptom = gate access)
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
    # Dan is a REAL default-tier user (GUEST:dan). "GUEST" has no dash, so
    # normalizer stripping doesn't affect it — dan resolves to default tier correctly.
    # Dan should NOT get write access (default tier = read only).
    # Trap_1 grants write to default+purchase → dan incorrectly gets write.
    r = _dispatch(patch_id, TRAP_CATCHING_INPUT)
    # dan should be denied write
    passed = r["gate"] is False
    return passed, f"gate={r['gate']}, tier={r['tier']}", "real_default_user_dan"


def _run_invariant_generalization(patch_id):
    # DEPT- prefix user
    r = _dispatch(patch_id, GENERALIZATION_INPUT)
    # carol (DEPT-50, editor, growth) should have write
    passed = r["gate"] is True and r["tier"] == "growth"
    return passed, f"gate={r['gate']}, tier={r['tier']}, org={r.get('resolved_org_id')}", "dept_prefix_carol"


def _run_invariant_causal_location(patch_id):
    # Check normalizer output directly: org_id must match canonical schema
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
    # audit_org must match the org_id used by the gate
    # For root fix: both are "ORG-100"
    # For trap_4/5: gate may see "ORG-100" but audit sees stripped "100"
    main_path_org = r["resolved_org_id"]
    bypass_org = r["audit_org"]
    consistent = main_path_org == bypass_org
    return consistent, f"main={main_path_org}, bypass={bypass_org}", None


def _run_invariant_chain_integrity(patch_id):
    r = _dispatch(patch_id, PRIMARY_INPUT)
    # Check: normalized org_id and resolved org_id must be consistent
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
            ChainNode("context_normalizer", "normalizer.py", "normalize", "canonicalizes fields — BUG: strips org prefix"),
            ChainNode("permission_resolver", "resolver.py", "resolve_permissions", "maps org+user to tier/permissions"),
            ChainNode("resource_gate", "gate.py", "check_gate", "enforces permission on resource"),
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
                     "adds correct case_data at corruption node; looks like careful migration",
                     "audit_logger reads org_id (not canonical_org_id) → sees stripped value",
                     "cross_path", None),
        ],
        invariants=[
            InvariantSpec("trap_catching",
                          "second user (bob, starter) must NOT have write permission",
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
