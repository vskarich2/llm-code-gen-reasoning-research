"""Product catalog with two-layer cache integration."""

from cache import put_local, put_shared, invalidate_shared, invalidate_local

_db = {}


def add_product(product_id, name, price):
    """Add product to database."""
    _db[product_id] = {"name": name, "price": price}


def db_get(product_id):
    """Raw DB lookup."""
    p = _db.get(product_id)
    return dict(p) if p else None


def update_product(product_id, **fields):
    """Update product in DB and invalidate caches.

    Invariant: after update, all cache layers must be invalidated.
    """
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    invalidate_shared(product_id)
    # BUG: local cache not invalidated — api.get_product reads local first
    return True


def reset():
    """Clear DB."""
    _db.clear()
