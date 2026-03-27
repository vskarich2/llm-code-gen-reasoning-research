"""Test for cache_invalidation_order: update_record must invalidate+set cache.

Invariant: After update_record("k1", "v1") then update_record("k1", "v2"),
read_record("k1") must return "v2". If update_record does not properly
update the cache (e.g., only writes to DB without cache invalidation/set),
subsequent reads from cache return stale data.
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

    try:
        update_record("k1", "v1")
        # Prime the cache by reading
        r1 = read_record("k1")
        if r1 != "v1":
            return False, [f"first read returned {r1!r}, expected 'v1'"]

        # Second update
        update_record("k1", "v2")
        r2 = read_record("k1")
    except Exception as e:
        return False, [f"raised: {e}"]

    if r2 != "v2":
        return False, [f"stale cache: read_record returned {r2!r}, expected 'v2'"]

    return True, ["cache properly updated after second write"]
