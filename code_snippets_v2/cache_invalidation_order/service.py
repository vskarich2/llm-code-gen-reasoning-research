from db import db_write, db_read
from cache import cache_set, cache_get, cache_invalidate, cache_get_version, cache_conditional_set


def update_record(key, value):
    db_write("records", key, value)


def read_record(key):
    cached = cache_get(key)
    if cached is not None:
        return cached
    val = db_read("records", key)
    if val is not None:
        cache_set(key, val)
    return val


def safe_update(key, value):
    ver = cache_get_version(key)
    db_write("records", key, value)
    cache_conditional_set(key, value, ver)


def delete_record(key):
    db_write("records", key, None)
    cache_invalidate(key)
