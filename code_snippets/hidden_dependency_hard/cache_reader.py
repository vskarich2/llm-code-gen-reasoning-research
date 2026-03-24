from cache_writer import _store


def get_display_name(user_id):
    return _store.get(f"user:{user_id}")


def is_user_cached(user_id):
    return f"user:{user_id}" in _store


def format_user_label(user_id):
    name = get_display_name(user_id)
    return f"@{name}" if name else "@Unknown"


def get_cache_stats():
    return {"size": len(_store), "keys": list(_store.keys())[:10]}
