_store = {}


def cache_put(key, value):
    _store[key] = value


def cache_delete(key):
    _store.pop(key, None)


def cache_put_if_absent(key, value):
    if key not in _store:
        _store[key] = value


def cache_clear_prefix(prefix):
    to_remove = [k for k in _store if k.startswith(prefix)]
    for k in to_remove:
        del _store[k]


def refresh_user_snapshot(user):
    cache_put_if_absent(f"user:{user['id']}", user["name"])


def sync_user_to_cache(user):
    cache_put(f"user:{user['id']}", user["name"])
