

from cache import get_local, get_shared, put_local, put_shared
from catalog import db_get

def get_product(product_id):
    result = get_local(product_id)
    if result is not None:
        return result

    result = get_shared(product_id)
    if result is not None:
        put_local(product_id, result)
        return result

    result = db_get(product_id)
    if result is not None:
        put_shared(product_id, result)
        put_local(product_id, result)
    return result


def format_product(product_id):
    p = get_product(product_id)
    if p is None:
        return "Not found"
    return f"{p['name']}: ${p['price']}"
