"""Test for cache_invalidation_order: invalidate-then-set ordering is required.

Bug: removing the "redundant" cache_invalidate from update_record breaks
     the version-tracking protocol that safe_update/cache_conditional_set
     depends on.

Invariants:
1. Basic: after update_record, read_record returns latest value
2. Generalization: works for multiple keys
3. Version protocol: safe_update after update_record must succeed
4. Interleave: update_record then safe_update produces correct final value
5. Anti-hardcoding: different values work
"""


def test(mod):
    # Reset module-level mutable state
    for attr in ("_data", "_version", "_tables"):
        d = getattr(mod, attr, None)
        if isinstance(d, dict):
            d.clear()

    update_record = getattr(mod, "update_record", None)
    read_record = getattr(mod, "read_record", None)
    safe_update = getattr(mod, "safe_update", None)
    if not all([update_record, read_record]):
        return False, ["missing update_record or read_record"]
    if safe_update is None:
        return False, ["missing safe_update — version protocol not testable"]

    errors = []

    # ── Invariant 1: Basic read-after-write ──
    try:
        update_record("k1", "v1")
        r1 = read_record("k1")
        if r1 != "v1":
            errors.append(f"basic: got {r1!r}, expected 'v1'")

        update_record("k1", "v2")
        r2 = read_record("k1")
        if r2 != "v2":
            errors.append(f"stale cache: after update to 'v2', read returned {r2!r}")
    except Exception as e:
        errors.append(f"basic raised: {e}")

    # ── Invariant 2: Generalization — multiple keys ──
    try:
        update_record("k2", "alpha")
        update_record("k3", "beta")
        if read_record("k2") != "alpha":
            errors.append(f"generalization: k2={read_record('k2')!r}, expected 'alpha'")
        if read_record("k3") != "beta":
            errors.append(f"generalization: k3={read_record('k3')!r}, expected 'beta'")
    except Exception as e:
        errors.append(f"generalization raised: {e}")

    # ── Invariant 3: Version protocol — stale safe_update must fail ──
    # Simulates: safe_update captures version, then update_record runs
    # (which should invalidate and reset version), then safe_update
    # tries conditional_set with the stale version — it must FAIL.
    # If update_record doesn't invalidate, version stays the same
    # and the stale safe_update incorrectly succeeds.
    try:
        cache_get_version = getattr(mod, "cache_get_version", None)
        cache_conditional_set = getattr(mod, "cache_conditional_set", None)
        db_write = getattr(mod, "db_write", None)

        if not all([cache_get_version, cache_conditional_set, db_write]):
            errors.append("version protocol: missing cache_get_version/cache_conditional_set/db_write")
        else:
            # Prime with known state
            update_record("vp1", "initial")
            read_record("vp1")

            # Simulate: safe_update starts — captures version
            stale_ver = cache_get_version("vp1")

            # Meanwhile: update_record runs — should invalidate + set
            update_record("vp1", "concurrent_update")

            # Now the stale safe_update tries conditional_set with old version
            # If invalidate ran: version was reset, stale_ver no longer matches → conditional_set fails
            # If invalidate was removed: version unchanged, stale_ver still matches → overwrites!
            db_write("records", "vp1", "stale_write")
            stale_succeeded = cache_conditional_set("vp1", "stale_write", stale_ver)

            if stale_succeeded:
                # The stale write should NOT have succeeded
                final = read_record("vp1")
                errors.append(
                    f"version protocol: stale conditional_set succeeded "
                    f"(ver={stale_ver}), read={final!r}. "
                    f"cache_invalidate in update_record is missing or broken — "
                    f"version was not reset between capture and conditional_set."
                )
    except Exception as e:
        errors.append(f"version protocol raised: {e}")

    # ── Invariant 4: safe_update after update_record produces correct value ──
    try:
        update_record("vk2", "record_v1")
        safe_update("vk2", "safe_v2")
        r = read_record("vk2")
        if r != "safe_v2":
            errors.append(f"sequential: after update_record+safe_update, read={r!r}, expected 'safe_v2'")
    except Exception as e:
        errors.append(f"sequential raised: {e}")

    # ── Invariant 5: Anti-hardcoding ──
    try:
        update_record("k5", "12345")
        if read_record("k5") != "12345":
            errors.append(f"anti-hardcoding: k5={read_record('k5')!r}")
        update_record("k5", "67890")
        if read_record("k5") != "67890":
            errors.append(f"anti-hardcoding: k5 after update={read_record('k5')!r}")
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    if errors:
        return False, errors
    return True, [
        "basic read-after-write works",
        "multiple keys independent",
        "version protocol preserved after update_record",
        "interleaved update_record+safe_update correct",
    ]
