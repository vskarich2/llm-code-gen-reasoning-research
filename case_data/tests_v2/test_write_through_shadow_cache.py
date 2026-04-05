"""Tests for write_through_shadow_cache family.

Invariant: warm reads after writes must reflect repository state.
Snapshot preservation must use repository freshness authority.

Bug: refresh_snapshot compares snapshot version against cache version.
After write, cache is invalidated (data removed) but cache version index
still holds the old version. Snapshot version == cache version, so
preservation passes and stale snapshot persists.
"""


def test(mod):
    errors = []

    # Reset all layers
    for fn_name in ("clear_repo", "clear_cache", "clear_snapshots", "clear_versions"):
        fn = getattr(mod, fn_name, None)
        if fn:
            fn()

    create_user = getattr(mod, "create_user", None)
    read_user = getattr(mod, "read_user", None)
    rename_user = getattr(mod, "rename_user", None)

    if not all([create_user, read_user, rename_user]):
        return False, ["create_user, read_user, or rename_user not found"]

    # ── Invariant 1: warm read after rename returns new name ──
    # Sequence: create → read (populates snapshot) → rename → read
    try:
        create_user("u1", "Alice")
        read_user("u1")  # populates snapshot + cache with version 1

        rename_user("u1", "Alicia")  # repo → version 2, cache invalidated, snapshot refreshed

        result = read_user("u1")  # warm read — hits snapshot first
        if result["display_name"] != "Alicia":
            errors.append(
                f"invariant 1: warm read after rename returned "
                f"'{result['display_name']}', expected 'Alicia'. "
                f"Stale snapshot persisted."
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # ── Invariant 2: cold read (no prior population) works correctly ──
    for fn_name in ("clear_repo", "clear_cache", "clear_snapshots", "clear_versions"):
        fn = getattr(mod, fn_name, None)
        if fn:
            fn()
    try:
        create_user("u2", "Bob")
        rename_user("u2", "Bobby")
        result2 = read_user("u2")
        if result2["display_name"] != "Bobby":
            errors.append(
                f"invariant 2: cold read after rename returned "
                f"'{result2['display_name']}', expected 'Bobby'"
            )
    except Exception as e:
        errors.append(f"invariant 2 raised: {e}")

    # ── Invariant 3: repeated warm reads remain consistent ──
    for fn_name in ("clear_repo", "clear_cache", "clear_snapshots", "clear_versions"):
        fn = getattr(mod, fn_name, None)
        if fn:
            fn()
    try:
        create_user("u3", "Charlie")
        read_user("u3")  # populate
        rename_user("u3", "Chuck")

        r1 = read_user("u3")
        r2 = read_user("u3")
        r3 = read_user("u3")
        if r1["display_name"] != "Chuck":
            errors.append(f"invariant 3: first read={r1['display_name']!r}")
        if r2["display_name"] != "Chuck":
            errors.append(f"invariant 3: second read={r2['display_name']!r}")
        if r3["display_name"] != "Chuck":
            errors.append(f"invariant 3: third read={r3['display_name']!r}")
    except Exception as e:
        errors.append(f"invariant 3 raised: {e}")

    # ── Invariant 4: anti-hardcoding — different names ──
    for fn_name in ("clear_repo", "clear_cache", "clear_snapshots", "clear_versions"):
        fn = getattr(mod, fn_name, None)
        if fn:
            fn()
    try:
        create_user("u4", "Zara")
        read_user("u4")
        rename_user("u4", "Zena")
        result4 = read_user("u4")
        if result4["display_name"] != "Zena":
            errors.append(
                f"anti-hardcoding: got '{result4['display_name']}', expected 'Zena'"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # ── Invariant 5: snapshot version must reflect repo after write ──
    get_snapshot_version = getattr(mod, "get_snapshot_version", None)
    get_repo_version = getattr(mod, "get_repo_version", None)
    if get_snapshot_version and get_repo_version:
        sv = get_snapshot_version("u4")
        rv = get_repo_version("u4")
        if sv < rv:
            errors.append(
                f"version check: snapshot version {sv} < repo version {rv} "
                f"after write"
            )

    # ── Structural ──
    for name in ("create_user", "read_user", "rename_user", "get_snapshot",
                 "refresh_snapshot", "get_cached", "invalidate"):
        if not callable(getattr(mod, name, None)):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, [
        "warm read after rename correct",
        "cold read correct",
        "repeated reads consistent",
        "anti-hardcoding passed",
        "version consistency maintained",
    ]
