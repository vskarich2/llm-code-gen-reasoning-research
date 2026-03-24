_items = {}
_seq = 0


def insert(key, value):
    global _seq
    _seq += 1
    _items[key] = {"value": value, "seq": _seq}
    return _seq


def get(key):
    return _items.get(key)


def exists(key):
    return key in _items


def get_seq():
    return _seq


def clear():
    global _seq
    _items.clear()
    _seq = 0
