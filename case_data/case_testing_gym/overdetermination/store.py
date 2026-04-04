_data = {}
_versions = {}


def write(key, value, version=None):
    _data[key] = value
    if version is not None:
        _versions[key] = version


def read(key):
    return _data.get(key)


def get_version(key):
    return _versions.get(key, 0)


def reset():
    _data.clear()
    _versions.clear()
