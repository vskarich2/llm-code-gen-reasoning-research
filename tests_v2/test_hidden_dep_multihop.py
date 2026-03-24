"""Test for hidden_dep_multihop: save_user write-through cache must overwrite.

Invariant: After save_user({id: "u1", name: "Alice"}) then
save_user({id: "u1", name: "Bob"}), get_display_name("u1") must return "Bob".

The bug: consolidating sync_user_to_cache (cache_put, always overwrites) with
refresh_user_snapshot (cache_put_if_absent, won't overwrite) breaks the
write-through cache for save_user.
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

    try:
        save_user({"id": "u1", "name": "Alice"})
        name1 = get_display_name("u1")
        if name1 != "Alice":
            return False, [f"after first save, got {name1!r}, expected 'Alice'"]

        save_user({"id": "u1", "name": "Bob"})
        name2 = get_display_name("u1")
    except Exception as e:
        return False, [f"raised: {e}"]

    if name2 != "Bob":
        return False, [
            f"cache not overwritten: get_display_name returned {name2!r}, expected 'Bob'"
        ]

    return True, ["write-through cache correctly overwrites on save_user"]
