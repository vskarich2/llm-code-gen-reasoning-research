from version_index import set_cache_version

_cache = {}


def clear_cache():
    global _cache
    _cache = {}

def get_cached(user_id):
    return _cache.get(user_id)


def set_cached(user_id, profile):
    _cache[user_id] = profile
    set_cache_version(user_id, profile["version"])


def invalidate(user_id):
    _cache.pop(user_id, None)
