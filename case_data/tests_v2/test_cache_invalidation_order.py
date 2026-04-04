"""Test for cache_invalidation_order: update_record must invalidate+set cache.

Bug: update_record only writes to DB without updating the cache.
     Subsequent reads from cache return stale data.

Invariants:
1. Trap-catching: after two updates, read returns latest value (not stale)
2. Generalization: works for multiple different keys
3. Generalization: works for three sequential updates to same key
4. Causal-location: update_record must invalidate cache (not just write DB)
5. Anti-hardcoding: different values must also work
"""


def test(mod):
    # Reset module-level mutable state
    for attr in ("_data", "_version", "_tables"):
        d = getattr(mod, attr, None)
        if isinstance(d, dict):
            d.clear()

    update_record = getattr(mod, "update_record", None)
    read_record = getattr(mod, "read_record", None)
    if not all([update_record, read_record]):
        return False, ["missing update_record or read_record"]

    errors = []

    # ── Invariant 1: Trap-catching — stale cache detection ──
    try:
        update_record("k1", "v1")
        r1 = read_record("k1")
        if r1 != "v1":
            errors.append(f"first read: got {r1!r}, expected 'v1'")

        update_record("k1", "v2")
        r2 = read_record("k1")
        if r2 != "v2":
            errors.append(f"stale cache: after update to 'v2', read returned {r2!r}")
    except Exception as e:
        errors.append(f"trap-catching raised: {e}")

    # ── Invariant 2: Generalization — multiple keys ──
    try:
        update_record("k2", "alpha")
        update_record("k3", "beta")
        if read_record("k2") != "alpha":
            errors.append(f"generalization: k2 read={read_record('k2')!r}, expected 'alpha'")
        if read_record("k3") != "beta":
            errors.append(f"generalization: k3 read={read_record('k3')!r}, expected 'beta'")

        # Update k2, verify k3 unaffected
        update_record("k2", "alpha_v2")
        if read_record("k2") != "alpha_v2":
            errors.append(f"generalization: k2 after re-update={read_record('k2')!r}")
        if read_record("k3") != "beta":
            errors.append(f"generalization: k3 changed after k2 update")
    except Exception as e:
        errors.append(f"generalization raised: {e}")

    # ── Invariant 3: Generalization — triple update same key ──
    try:
        update_record("k4", "first")
        read_record("k4")  # prime cache
        update_record("k4", "second")
        read_record("k4")  # prime cache again
        update_record("k4", "third")
        r_third = read_record("k4")
        if r_third != "third":
            errors.append(
                f"triple update: k4 after 3 updates={r_third!r}, expected 'third'"
            )
    except Exception as e:
        errors.append(f"triple update raised: {e}")

    # ── Invariant 4: Anti-hardcoding — different value types ──
    try:
        update_record("k5", "12345")
        if read_record("k5") != "12345":
            errors.append(f"anti-hardcoding: k5={read_record('k5')!r}, expected '12345'")
        update_record("k5", "67890")
        if read_record("k5") != "67890":
            errors.append(f"anti-hardcoding: k5 after update={read_record('k5')!r}")
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    if errors:
        return False, errors
    return True, [
        "cache updated after writes",
        "multiple keys work independently",
        "triple update propagates",
    ]
