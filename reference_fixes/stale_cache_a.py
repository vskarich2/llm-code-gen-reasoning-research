"""Product catalog with caching."""

_db = {}
_cache = {}


def add_product(product_id, name, price):
    """Add a product to the database."""
    _db[product_id] = {"name": name, "price": price}


def get_product(product_id):
    """Get product by ID, using cache for repeated lookups."""
    if product_id in _cache:
        return _cache[product_id]
    product = _db.get(product_id)
    if product is not None:
        _cache[product_id] = dict(product)
    return _cache.get(product_id)


def update_product(product_id, **fields):
    """Update product fields in the database.

    Invariant: get_product() must return current data after update.
    """
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    _cache.pop(product_id, None)  # FIX: invalidate cache on update
    return True


def reset():
    """Clear all data."""
    _db.clear()
    _cache.clear()
