_data = {}
_version = {}


def cache_set(key, value, version=None):
    _data[key] = value
    _version[key] = version or 0


def cache_get(key):
    return _data.get(key)


def cache_get_version(key):
    return _version.get(key, -1)


def cache_invalidate(key):
    _data.pop(key, None)
    _version.pop(key, None)


def cache_conditional_set(key, value, expected_version):
    if _version.get(key, -1) == expected_version:
        _data[key] = value
        _version[key] = expected_version + 1
        return True
    return False
