_cache_versions = {}
_snapshot_versions = {}


def clear_versions():
    global _cache_versions, _snapshot_versions
    _cache_versions = {}
    _snapshot_versions = {}


def get_cache_version(user_id):
    return _cache_versions.get(user_id, 0)


def set_cache_version(user_id, version):
    _cache_versions[user_id] = version


def get_snapshot_version(user_id):
    return _snapshot_versions.get(user_id, 0)


def set_snapshot_version(user_id, version):
    _snapshot_versions[user_id] = version
