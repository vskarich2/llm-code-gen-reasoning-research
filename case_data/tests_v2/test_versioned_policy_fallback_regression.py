"""Tests for versioned_policy_fallback_regression family (A, B, C/L3).

Invariant: execution behavior must match the resolved policy version for
each request. Prior requests must not influence subsequent execution.

A: shallow copy aliasing in compat.py (2 files, no resolver)
B: shallow copy with build_base_context (3 files, with resolver)
C/L3: shared mutable dict across requests (4 files, full system)
"""


def _make_resolved(version):
    """Helper: construct a resolved policy dict."""
    policies = {
        "v1": {"version": "v1", "behavior": "legacy", "fallback": True},
        "v3": {"version": "v3", "behavior": "latest", "fallback": False},
    }
    return {"resolved_version": version, "policy": policies[version]}


def _run_cross_request_test(mod, errors, label, use_resolver=False):
    """Core test: legacy request must not contaminate subsequent v3 request."""
    attach = getattr(mod, "attach_compatibility_context", None)
    execute = getattr(mod, "execute_policy", None)
    resolve = getattr(mod, "resolve_policy", None) if use_resolver else None

    if not attach or not execute:
        errors.append(f"{label}: attach_compatibility_context or execute_policy not found")
        return

    def _resolve(req):
        if resolve:
            return resolve(req)
        version = "v1" if req.get("requires_legacy") else "v3"
        return _make_resolved(version)

    # 1. Fresh v3 must execute v3
    req1 = {"id": 1, "requires_legacy": False}
    resolved1 = _resolve(req1)
    req1 = attach(req1, resolved1)
    result1 = execute(req1, resolved1)
    if result1["executed_version"] != "v3":
        errors.append(f"{label}: fresh v3 executed {result1['executed_version']}, expected v3")

    # 2. Legacy must execute v1
    req2 = {"id": 2, "requires_legacy": True}
    resolved2 = _resolve(req2)
    req2 = attach(req2, resolved2)
    result2 = execute(req2, resolved2)
    if result2["executed_version"] != "v1":
        errors.append(f"{label}: legacy executed {result2['executed_version']}, expected v1")

    # 3. CRITICAL: v3 after legacy must still execute v3
    req3 = {"id": 3, "requires_legacy": False}
    resolved3 = _resolve(req3)
    req3 = attach(req3, resolved3)
    result3 = execute(req3, resolved3)
    if result3["executed_version"] != "v3":
        errors.append(
            f"{label}: v3 after legacy executed {result3['executed_version']}, "
            f"expected v3. Cross-request state leakage."
        )

    # 4. Anti-hardcoding: different ids
    req4 = {"id": 77, "requires_legacy": True}
    resolved4 = _resolve(req4)
    req4 = attach(req4, resolved4)
    execute(req4, resolved4)

    req5 = {"id": 78, "requires_legacy": False}
    resolved5 = _resolve(req5)
    req5 = attach(req5, resolved5)
    result5 = execute(req5, resolved5)
    if result5["executed_version"] != "v3":
        errors.append(f"{label}: anti-hardcoding req 78 executed {result5['executed_version']}")


def test_a(mod):
    """Level A: shallow copy aliasing, 2 files (compat + executor)."""
    errors = []
    _run_cross_request_test(mod, errors, "A", use_resolver=False)

    for name in ("attach_compatibility_context", "execute_policy"):
        if not callable(getattr(mod, name, None)):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, ["no cross-request aliasing", "fallback correct", "anti-hardcoding passed"]


def test_b(mod):
    """Level B: shallow copy via build_base_context, 3 files."""
    errors = []
    _run_cross_request_test(mod, errors, "B", use_resolver=True)

    for name in ("attach_compatibility_context", "execute_policy", "resolve_policy"):
        if not callable(getattr(mod, name, None)):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, ["no cross-request aliasing", "fallback correct", "resolver correct", "anti-hardcoding passed"]


def test_c(mod):
    """Level C/L3: shared mutable dict, 4 files (full system)."""
    errors = []
    _run_cross_request_test(mod, errors, "C", use_resolver=True)

    # Additional L3 check: resolver always returns correct version
    resolve = getattr(mod, "resolve_policy", None)
    if resolve:
        r_fresh = resolve({"id": 50, "requires_legacy": False})
        if r_fresh["resolved_version"] != "v3":
            errors.append(f"resolver: returned {r_fresh['resolved_version']}, expected v3")
        r_legacy = resolve({"id": 51, "requires_legacy": True})
        if r_legacy["resolved_version"] != "v1":
            errors.append(f"resolver: legacy returned {r_legacy['resolved_version']}, expected v1")

    for name in ("attach_compatibility_context", "execute_policy", "resolve_policy"):
        if not callable(getattr(mod, name, None)):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, ["no cross-request leakage", "fallback correct", "resolver correct", "anti-hardcoding passed"]


# Default test (for cases without explicit difficulty)
def test(mod):
    return test_c(mod)
