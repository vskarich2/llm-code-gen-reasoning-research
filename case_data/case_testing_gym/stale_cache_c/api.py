"""API layer: reads through two-layer cache."""

from cache import get_local, get_shared, put_local, put_shared
from catalog import db_get


def get_product(product_id):
    """Get product through cache layers: local -> shared -> DB."""
    # Check local cache first
    result = get_local(product_id)
    if result is not None:
        return result

    # Check shared cache
    result = get_shared(product_id)
    if result is not None:
        put_local(product_id, result)
        return result

    # Fall through to DB
    result = db_get(product_id)
    if result is not None:
        put_shared(product_id, result)
        put_local(product_id, result)
    return result


def format_product(product_id):
    """Format product for display (distractor)."""
    p = get_product(product_id)
    if p is None:
        return "Not found"
    return f"{p['name']}: ${p['price']}"
