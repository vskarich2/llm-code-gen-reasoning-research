"""Tests for misleading_local_fix family.

Invariant: display_name must remain consistent with first after update_name.
Bug: update_name changes first/last but doesn't recompute display_name.
"""


def test(mod):
    errors = []

    User = getattr(mod, "User", None)
    if User is None:
        return False, ["User class not found"]

    # ── Invariant 1: display_name updates after update_name ──
    try:
        u = User("bob", "jones")
        p1 = u.profile()
        if p1["display_name"] != "Bob":
            errors.append(f"invariant 1: initial display_name={p1['display_name']!r}, expected 'Bob'")

        u.update_name("alice", "smith")
        p2 = u.profile()
        if p2["display_name"] != "Alice":
            errors.append(
                f"invariant 1: after update_name('alice','smith'), "
                f"display_name={p2['display_name']!r}, expected 'Alice'"
            )
        if p2["first"] != "alice":
            errors.append(f"invariant 1: first={p2['first']!r}, expected 'alice'")
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # ── Invariant 2: multiple updates stay consistent ──
    try:
        u2 = User("x", "y")
        u2.update_name("charlie", "brown")
        u2.update_name("dave", "white")
        p3 = u2.profile()
        if p3["display_name"] != "Dave":
            errors.append(
                f"invariant 2: after two updates, "
                f"display_name={p3['display_name']!r}, expected 'Dave'"
            )
    except Exception as e:
        errors.append(f"invariant 2 raised: {e}")

    # ── Invariant 3: anti-hardcoding — different names ──
    try:
        u3 = User("zara", "quinn")
        u3.update_name("max", "reed")
        p4 = u3.profile()
        if p4["display_name"] != "Max":
            errors.append(
                f"anti-hardcoding: display_name={p4['display_name']!r}, expected 'Max'"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # ── Structural ──
    for name in ("User",):
        if not hasattr(mod, name):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, [
        "display_name synced after update",
        "multiple updates consistent",
        "anti-hardcoding passed",
    ]
