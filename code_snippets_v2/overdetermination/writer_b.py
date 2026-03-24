from store import write

_cache = {}


def write_cached(key, compute_fn):
    """Write from cache if available, else compute and cache."""
    if key not in _cache:
        _cache[key] = compute_fn()
    write(key, _cache[key])  # no version update
    return _cache[key]


def reset():
    _cache.clear()
