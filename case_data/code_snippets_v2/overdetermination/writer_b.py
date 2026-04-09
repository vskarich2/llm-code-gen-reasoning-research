from store import write

_cache = {}


def write_cached(key, compute_fn):
    if key not in _cache:
        _cache[key] = compute_fn()
    write(key, _cache[key])
    return _cache[key]


def reset():
    _cache.clear()
