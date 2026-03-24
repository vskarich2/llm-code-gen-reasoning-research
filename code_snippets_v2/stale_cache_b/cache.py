"""Simple key-value cache."""

_store = {}


def get(key):
    """Return cached value or None."""
    return _store.get(key)


def put(key, value):
    """Store a value in the cache."""
    _store[key] = value


def invalidate(key):
    """Remove a key from the cache."""
    _store.pop(key, None)


def clear():
    """Clear entire cache."""
    _store.clear()
