from cache import put_local, put_shared, invalidate_shared, invalidate_local

_db = {}

def add_product(product_id, name, price):
    _db[product_id] = {"name": name, "price": price}


def db_get(product_id):
    p = _db.get(product_id)
    return dict(p) if p else None


def update_product(product_id, **fields):
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    invalidate_shared(product_id)

    return True


def reset():
    _db.clear()
