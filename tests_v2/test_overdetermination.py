"""Tests for overdetermination (L2 deep — stale cache masked by fresh writer).

Invariant: after two updates with different values, store contains the latest value.
"""


def test(mod):
    """Non-diagnostic: reports wrong value, does not name the cause."""
    if hasattr(mod, "reset"):
        mod.reset()

    mod.update_product("P1", lambda: 42)
    mod.update_product("P1", lambda: 99)

    result = mod.serve_request("P1")
    if result["value"] != 99:
        return False, [f"unexpected value after update: got {result['value']}, expected 99"]
    return True, ["product data correct after update"]
