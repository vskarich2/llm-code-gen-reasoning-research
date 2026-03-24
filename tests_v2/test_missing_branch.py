"""Tests for missing_branch family (edge_case_omission).

Invariant: All documented roles must receive their correct permissions.
           No valid role should silently get empty/no access.
"""


def test_a(mod):
    """Level A: moderator role missing from permissions dict."""
    # No state reset needed — ROLE_PERMISSIONS is part of the code logic,
    # not mutable runtime state. The fix adds moderator to the dict.

    get_perms = getattr(mod, "get_permissions", None)
    if get_perms is None:
        return False, ["get_permissions not found"]

    try:
        perms = get_perms("moderator")
    except Exception as e:
        return False, [f"get_permissions raised: {e}"]

    if not perms:
        return False, ["moderator got empty permissions, expected non-empty set"]

    if "read" not in perms:
        return False, [f"moderator missing 'read' permission, got: {perms}"]

    if "delete" not in perms:
        return False, [f"moderator missing 'delete' permission, got: {perms}"]

    return True, ["moderator gets correct permissions"]


def test_b(mod):
    """Level B: guest role missing from dispatch table."""
    get_access = getattr(mod, "get_access", None)
    can_read = getattr(mod, "can_read", None)

    if get_access is None:
        return False, ["get_access not found"]

    try:
        access = get_access("guest")
    except Exception as e:
        return False, [f"get_access raised: {e}"]

    if not access.get("read"):
        return False, [f"guest has no read access, expected read-only. Got: {access}"]

    # Guest should NOT have write or delete
    if access.get("write"):
        return False, [f"guest should not have write access, got: {access}"]

    if access.get("delete"):
        return False, [f"guest should not have delete access, got: {access}"]

    return True, ["guest gets correct read-only access"]


def test_c(mod):
    """Level C: service_account passes middleware but fails in handler."""
    authorize = getattr(mod, "authorize", None)
    if authorize is None:
        return False, ["authorize not found"]

    try:
        result = authorize({"role": "service_account"})
    except Exception as e:
        return False, [f"authorize raised: {e}"]

    if not result.get("can_read"):
        return False, [
            f"service_account got can_read=False, expected True. "
            f"Middleware allows it but handler doesn't. Got: {result}"
        ]

    if not result.get("can_write"):
        return False, [
            f"service_account got can_write=False, expected True. Got: {result}"
        ]

    # service_account should NOT have admin privileges
    if result.get("can_admin"):
        return False, [
            f"service_account got can_admin=True, expected False. Got: {result}"
        ]

    return True, ["service_account gets correct read+write access"]
