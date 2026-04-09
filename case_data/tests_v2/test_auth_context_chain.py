"""Tests for auth_context_chain.

Bug: context_normalizer strips org_id prefix (ORG-100 -> 100).
Fix: preserve org_id as-is in normalize_context.
"""


def test(mod):
    errors = []

    normalize_context = getattr(mod, "normalize_context", None)
    resolve_permissions_node = getattr(mod, "resolve_permissions_node", None)
    check_gate_node = getattr(mod, "check_gate_node", None)
    if not normalize_context or not resolve_permissions_node or not check_gate_node:
        return False, ["required functions not found: normalize_context, resolve_permissions_node, check_gate_node"]

    # Invariant 1: org_id preserved after normalization
    parsed = {"org_id": "ORG-100", "user": "alice", "action": "PURCHASE", "required_permission": "write"}
    normalized = normalize_context(parsed)
    if normalized["org_id"] != "ORG-100":
        errors.append(f"invariant 1: org_id={normalized['org_id']!r}, expected 'ORG-100'")

    # Invariant 2: alice (enterprise) gets write access
    if not errors:
        resolved = resolve_permissions_node(normalized)
        result = check_gate_node(resolved)
        if not result["granted"]:
            errors.append(f"invariant 2: alice write denied, tier={result['tier']!r}")
        if result["tier"] != "enterprise":
            errors.append(f"invariant 2: alice tier={result['tier']!r}, expected 'enterprise'")

    # Invariant 3: DEPT-50 carol (growth) gets write access
    parsed_carol = {"org_id": "DEPT-50", "user": "carol", "action": "PURCHASE", "required_permission": "write"}
    normalized_carol = normalize_context(parsed_carol)
    if normalized_carol["org_id"] != "DEPT-50":
        errors.append(f"invariant 3: carol org_id={normalized_carol['org_id']!r}, expected 'DEPT-50'")
    else:
        resolved_carol = resolve_permissions_node(normalized_carol)
        result_carol = check_gate_node(resolved_carol)
        if not result_carol["granted"]:
            errors.append(f"invariant 3: carol write denied, tier={result_carol['tier']!r}")

    # Invariant 4: GUEST:dan (default) denied write
    parsed_dan = {"org_id": "GUEST", "user": "dan", "action": "PURCHASE", "required_permission": "write"}
    normalized_dan = normalize_context(parsed_dan)
    resolved_dan = resolve_permissions_node(normalized_dan)
    result_dan = check_gate_node(resolved_dan)
    if result_dan["granted"]:
        errors.append(f"invariant 4: dan (default) incorrectly granted write, tier={result_dan['tier']!r}")

    return not errors, errors
