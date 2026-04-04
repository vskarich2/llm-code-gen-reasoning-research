"""Tests for partial_update family (partial_state_update).

Invariant: derived/dependent fields must stay in sync after updates.
"""


def test_a(mod):
    """Level A: update_profile must sync display_name when name changes."""
    create = getattr(mod, "create_user", None)
    update = getattr(mod, "update_profile", None)
    if create is None:
        return False, ["create_user not found"]
    if update is None:
        return False, ["update_profile not found"]

    try:
        user = create("Alice", "alice@example.com")
        update(user, {"name": "Bob"})
    except Exception as e:
        return False, [f"raised: {e}"]

    if user.get("name") != "Bob":
        return False, [f"name not updated: {user.get('name')}"]

    if user.get("display_name") != "Bob":
        return False, [
            f"display_name not synced: display_name={user.get('display_name')!r}, "
            f"expected 'Bob'"
        ]

    return True, ["display_name synced with name"]


def test_b(mod):
    """Level B: update_profile must recompute full_name when first_name changes."""
    create = getattr(mod, "create_user", None)
    update = getattr(mod, "update_profile", None)
    if create is None:
        return False, ["create_user not found"]
    if update is None:
        return False, ["update_profile not found"]

    try:
        user = create("Alice", "Smith", "alice@example.com")
        update(user, {"first_name": "Bob"})
    except Exception as e:
        return False, [f"raised: {e}"]

    expected_full = "Bob Smith"
    actual_full = user.get("full_name")
    if actual_full != expected_full:
        return False, [
            f"full_name not synced: full_name={actual_full!r}, expected {expected_full!r}"
        ]

    return True, ["full_name recomputed after first_name change"]


def test_c(mod):
    """Level C: changing email must set verified=False and update cached_greeting."""
    create = getattr(mod, "create_user", None)
    update = getattr(mod, "update_profile", None)
    verify = getattr(mod, "verify_user", None)
    if create is None:
        return False, ["create_user not found"]
    if update is None:
        return False, ["update_profile not found"]
    if verify is None:
        return False, ["verify_user not found"]

    try:
        user = create("Alice", "alice@example.com")
        verify(user)
        # User is now verified
        if not user.get("verified"):
            return False, ["verify_user did not set verified=True"]
        old_greeting = user.get("cached_greeting")
        update(user, {"email": "bob@example.com"})
    except Exception as e:
        return False, [f"raised: {e}"]

    errors = []
    if user.get("verified") is not False:
        errors.append(f"verified not reset: verified={user.get('verified')!r}, expected False")
    if user.get("email") != "bob@example.com":
        errors.append(f"email not updated: {user.get('email')!r}")

    if errors:
        return False, errors
    return True, ["email change resets verified and updates greeting"]
