"""Tests for stale_cache family (hidden_dependency).

Invariant: get_product() must return current data after update_product().
"""


def test_a(mod):
    """Level A: single-file cache not invalidated on update."""
    reset = getattr(mod, "reset", None)
    if reset:
        reset()

    # Clear module-level dicts directly as fallback
    for attr in ("_db", "_cache"):
        d = getattr(mod, attr, None)
        if isinstance(d, dict):
            d.clear()

    add = getattr(mod, "add_product", None)
    get = getattr(mod, "get_product", None)
    update = getattr(mod, "update_product", None)
    if not all([add, get, update]):
        return False, ["missing add_product, get_product, or update_product"]

    try:
        add("p1", "Widget", 10.0)
        # Prime the cache
        result1 = get("p1")
        if result1 is None:
            return False, ["get_product returned None after add"]

        # Update price
        update("p1", price=25.0)

        # Read again — should reflect update
        result2 = get("p1")
    except Exception as e:
        return False, [f"raised: {e}"]

    if result2 is None:
        return False, ["get_product returned None after update"]

    if result2.get("price") != 25.0:
        return False, [
            f"stale cache: price={result2.get('price')}, expected 25.0"
        ]

    return True, ["cache invalidated on update"]


def test_b(mod):
    """Level B: cross-file cache not invalidated by catalog.update_product."""
    reset = getattr(mod, "reset", None)
    if reset:
        reset()

    for attr in ("_db",):
        d = getattr(mod, attr, None)
        if isinstance(d, dict):
            d.clear()

    add = getattr(mod, "add_product", None)
    get = getattr(mod, "get_product", None)
    update = getattr(mod, "update_product", None)
    if not all([add, get, update]):
        return False, ["missing add_product, get_product, or update_product"]

    try:
        add("p1", "Widget", 10.0)
        result1 = get("p1")
        if result1 is None:
            return False, ["get_product returned None after add"]

        update("p1", price=25.0)
        result2 = get("p1")
    except Exception as e:
        return False, [f"raised: {e}"]

    if result2 is None:
        return False, ["get_product returned None after update"]

    if result2.get("price") != 25.0:
        return False, [
            f"stale cache: price={result2.get('price')}, expected 25.0"
        ]

    return True, ["cross-file cache invalidated on update"]


def test_c(mod):
    """Level C: two-layer cache — local layer not invalidated."""
    # Reset everything
    reset = getattr(mod, "reset", None)
    if reset:
        reset()
    clear_all = getattr(mod, "clear_all", None)
    if clear_all:
        clear_all()

    for attr in ("_db", "_local", "_shared"):
        d = getattr(mod, attr, None)
        if isinstance(d, dict):
            d.clear()

    add = getattr(mod, "add_product", None)
    get = getattr(mod, "get_product", None)
    update = getattr(mod, "update_product", None)
    if not all([add, get, update]):
        return False, ["missing add_product, get_product, or update_product"]

    try:
        add("p1", "Widget", 10.0)
        # Prime both cache layers
        result1 = get("p1")
        if result1 is None:
            return False, ["get_product returned None after add"]

        # Update product
        update("p1", price=50.0)

        # Read again — should see updated price
        result2 = get("p1")
    except Exception as e:
        return False, [f"raised: {e}"]

    if result2 is None:
        return False, ["get_product returned None after update"]

    if result2.get("price") != 50.0:
        return False, [
            f"stale local cache: price={result2.get('price')}, expected 50.0"
        ]

    return True, ["both cache layers invalidated on update"]
