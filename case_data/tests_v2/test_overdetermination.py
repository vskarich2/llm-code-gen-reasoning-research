"""Tests for overdetermination (L2 deep — stale cache masked by fresh writer).

Bug: update_product calls both write_fresh (correct, versioned) and write_cached
     (stale, unversioned). write_cached overwrites the fresh value with a cached
     stale value on second update.

Fix: remove the write_cached call from update_product.

Invariants:
1. Trap-catching: after two updates, value must be latest (not stale cached)
2. Generalization: version must increment on each update (write_fresh does this)
3. Causal-location: write_cached must not be called from update_product
4. Anti-hardcoding: different product IDs and values must also work
"""


def test(mod):
    if hasattr(mod, "reset"):
        mod.reset()
    # Reset writer state too
    for attr in ("_counter", "_cache"):
        obj = getattr(mod, attr, None)
        if isinstance(obj, dict):
            obj.clear()
        elif isinstance(obj, int):
            pass  # can't reset module-level int easily
    # Try calling reset on writer modules
    for name in dir(mod):
        if name.startswith("reset") and callable(getattr(mod, name)):
            try:
                getattr(mod, name)()
            except Exception:
                pass

    errors = []

    # ── Invariant 1: Trap-catching (original test) ──
    # After two updates with different values, store must have the latest
    mod.update_product("P1", lambda: 42)
    mod.update_product("P1", lambda: 99)

    result = mod.serve_request("P1")
    if result["value"] != 99:
        errors.append(
            f"trap-catching: after update(42) then update(99), "
            f"got value={result['value']}, expected 99"
        )

    # ── Invariant 2: Generalization — version tracking ──
    # write_fresh increments version; if write_cached is still called,
    # it writes without version → version stays at write_fresh's value
    # but the VALUE is wrong. Check that version increments properly.
    v1 = result.get("version", None)
    if v1 is not None and v1 < 1:
        errors.append(
            f"generalization: version={v1} after two updates, expected >= 2"
        )

    # Third update — version should increment again
    mod.update_product("P1", lambda: 200)
    result3 = mod.serve_request("P1")
    if result3["value"] != 200:
        errors.append(
            f"generalization: after 3rd update, value={result3['value']}, expected 200"
        )
    v3 = result3.get("version", None)
    if v3 is not None and v1 is not None and v3 <= v1:
        errors.append(
            f"generalization: version did not increment: v_after_2={v1}, v_after_3={v3}"
        )

    # ── Invariant 3: Causal-location — write_cached must not be called ──
    # If the fix keeps write_cached in update_product, the cache will cause
    # stale values. Check that a NEW product doesn't get cached stale values.
    mod.update_product("P2", lambda: 10)
    mod.update_product("P2", lambda: 20)
    r2 = mod.serve_request("P2")
    if r2["value"] != 20:
        errors.append(
            f"causal-location: P2 after update(10)+update(20), "
            f"value={r2['value']}, expected 20 (write_cached caching stale)"
        )

    # ── Invariant 4: Anti-hardcoding — different amounts ──
    mod.update_product("P3", lambda: 777)
    r3 = mod.serve_request("P3")
    if r3["value"] != 777:
        errors.append(
            f"anti-hardcoding: P3 value={r3['value']}, expected 777"
        )

    if errors:
        return False, errors
    return True, ["value correct after updates, versions increment, no stale cache"]
