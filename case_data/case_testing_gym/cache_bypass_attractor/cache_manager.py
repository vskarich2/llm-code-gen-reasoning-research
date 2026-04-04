from data_store import fetch


_cache = {}


def cache_get(key):
    if key in _cache:
        return _cache[key]
    result = fetch(key)
    # BUG: never writes result back to _cache
    return result


def invalidate(key):
    _cache.pop(key, None)


def clear():
    _cache.clear()


def cache_size():
    return len(_cache)


def reset():
    _cache.clear()
