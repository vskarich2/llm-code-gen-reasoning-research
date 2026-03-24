"""Two-layer cache: local (per-request) and shared (global)."""

_local = {}
_shared = {}


def get_local(key):
    """Read from local cache."""
    return _local.get(key)


def put_local(key, value):
    """Write to local cache."""
    _local[key] = value


def invalidate_local(key):
    """Remove key from local cache."""
    _local.pop(key, None)


def get_shared(key):
    """Read from shared cache."""
    return _shared.get(key)


def put_shared(key, value):
    """Write to shared cache."""
    _shared[key] = value


def invalidate_shared(key):
    """Remove key from shared cache."""
    _shared.pop(key, None)


def clear_all():
    """Clear both layers."""
    _local.clear()
    _shared.clear()
