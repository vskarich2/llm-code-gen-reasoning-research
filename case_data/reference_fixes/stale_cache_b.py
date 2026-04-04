"""Product catalog using external cache module."""

from cache import get, put, invalidate

_db = {}


def add_product(product_id, name, price):
    """Add a product to the database."""
    _db[product_id] = {"name": name, "price": price}


def get_product(product_id):
    """Get product, checking cache first."""
    cached = get(product_id)
    if cached is not None:
        return cached
    product = _db.get(product_id)
    if product is not None:
        put(product_id, dict(product))
    return _db.get(product_id)


def update_product(product_id, **fields):
    """Update product in DB.

    Invariant: subsequent get_product() must reflect the update.
    """
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    invalidate(product_id)  # FIX: invalidate cache after DB write
    return True


def reset():
    """Clear DB and cache."""
    _db.clear()
    from cache import clear

    clear()
