_store = {}

def get(key):
    return _store.get(key)


def put(key, value):
    _store[key] = value


def invalidate(key):
    _store.pop(key, None)


def clear():
    _store.clear()
