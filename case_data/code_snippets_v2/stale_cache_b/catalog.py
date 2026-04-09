from cache import get, put, invalidate

_db = {}

def add_product(product_id, name, price):
    _db[product_id] = {"name": name, "price": price}

def get_product(product_id):
    cached = get(product_id)
    if cached is not None:
        return cached
    product = _db.get(product_id)
    if product is not None:
        put(product_id, dict(product))
    return _db.get(product_id)


def update_product(product_id, **fields):
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    return True

def reset():
    _db.clear()
    from cache import clear
    clear()
