_db = {}
_cache = {}

def add_product(product_id, name, price):
    _db[product_id] = {"name": name, "price": price}

def get_product(product_id):
    if product_id in _cache:
        return _cache[product_id]
    product = _db.get(product_id)
    if product is not None:
        _cache[product_id] = dict(product)
    return _cache.get(product_id)

def update_product(product_id, **fields):
    if product_id not in _db:
        return False
    _db[product_id].update(fields)
    return True

def reset():
    _db.clear()
    _cache.clear()
