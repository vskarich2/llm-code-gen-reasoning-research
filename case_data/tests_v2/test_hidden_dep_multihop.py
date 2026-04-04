"""Test for hidden_dep_multihop: save_user write-through cache must overwrite.

Bug: save_user calls refresh_user_snapshot (cache_put_if_absent, won't overwrite)
     instead of sync_user_to_cache (cache_put, always overwrites).

Fix: change save_user to call sync_user_to_cache.

Invariants:
1. Trap-catching: save same user twice with different name → cache returns latest
2. Generalization: works for multiple users saved in sequence
3. Causal-location: rename_user must also update cache correctly
4. Anti-hardcoding: third name update must also propagate
"""


def test(mod):
    # Reset module-level mutable state
    store = getattr(mod, "_store", None)
    if isinstance(store, dict):
        store.clear()
    rows = getattr(mod, "_rows", None)
    if isinstance(rows, dict):
        rows.clear()
    db = getattr(mod, "db", None)
    if db is not None and hasattr(db, "_rows"):
        db._rows.clear()

    save_user = getattr(mod, "save_user", None)
    get_display_name = getattr(mod, "get_display_name", None)
    if not all([save_user, get_display_name]):
        return False, ["missing save_user or get_display_name"]

    errors = []

    # ── Invariant 1: Trap-catching — cache overwrite on re-save ──
    try:
        save_user({"id": "u1", "name": "Alice"})
        name1 = get_display_name("u1")
        if name1 != "Alice":
            errors.append(f"after first save, got {name1!r}, expected 'Alice'")

        save_user({"id": "u1", "name": "Bob"})
        name2 = get_display_name("u1")
        if name2 != "Bob":
            errors.append(
                f"cache not overwritten: get_display_name returned {name2!r}, expected 'Bob'"
            )
    except Exception as e:
        errors.append(f"trap-catching raised: {e}")

    # ── Invariant 2: Generalization — multiple users ──
    try:
        save_user({"id": "u2", "name": "Carol"})
        save_user({"id": "u3", "name": "Dave"})

        n2 = get_display_name("u2")
        n3 = get_display_name("u3")
        if n2 != "Carol":
            errors.append(f"generalization: u2 name={n2!r}, expected 'Carol'")
        if n3 != "Dave":
            errors.append(f"generalization: u3 name={n3!r}, expected 'Dave'")

        # Update u2 and verify u3 is unaffected
        save_user({"id": "u2", "name": "Carol_v2"})
        if get_display_name("u2") != "Carol_v2":
            errors.append(f"generalization: u2 after re-save not updated")
        if get_display_name("u3") != "Dave":
            errors.append(f"generalization: u3 changed after u2 re-save")
    except Exception as e:
        errors.append(f"generalization raised: {e}")

    # ── Invariant 3: Causal-location — rename_user must also work ──
    rename_user = getattr(mod, "rename_user", None)
    if rename_user is not None:
        try:
            rename_user("u1", "Bob_renamed")
            name_after_rename = get_display_name("u1")
            if name_after_rename != "Bob_renamed":
                errors.append(
                    f"causal-location: after rename_user, got {name_after_rename!r}, "
                    f"expected 'Bob_renamed' (rename_user may also use wrong cache function)"
                )
        except Exception as e:
            errors.append(f"causal-location: rename_user raised: {e}")

    # ── Invariant 4: Anti-hardcoding — third update ──
    try:
        save_user({"id": "u1", "name": "Eve"})
        if get_display_name("u1") != "Eve":
            errors.append(
                f"anti-hardcoding: third update to u1, got {get_display_name('u1')!r}, expected 'Eve'"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    if errors:
        return False, errors
    return True, [
        "write-through cache overwrites on save_user",
        "multiple users work independently",
        "rename_user updates cache",
    ]
