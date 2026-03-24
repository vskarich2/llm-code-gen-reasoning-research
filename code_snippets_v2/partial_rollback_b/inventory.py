"""Inventory management with reservation tracking."""

_stock = {}
_reserved = {}


def reset():
    global _stock, _reserved
    _stock = {}
    _reserved = {}


def add_product(product_id, quantity):
    _stock[product_id] = _stock.get(product_id, 0) + quantity
    _reserved.setdefault(product_id, 0)


def reserve(product_id, qty):
    avail = _stock.get(product_id, 0) - _reserved.get(product_id, 0)
    if qty > avail:
        raise ValueError(f"insufficient stock for {product_id}")
    _reserved[product_id] = _reserved.get(product_id, 0) + qty


def release(product_id, qty):
    _reserved[product_id] = _reserved.get(product_id, 0) - qty


def available(product_id):
    return _stock.get(product_id, 0) - _reserved.get(product_id, 0)


def get_reserved(product_id):
    return _reserved.get(product_id, 0)
