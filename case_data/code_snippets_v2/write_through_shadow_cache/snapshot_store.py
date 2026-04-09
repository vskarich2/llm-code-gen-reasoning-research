_snapshots = {}

from version_index import get_cache_version, get_snapshot_version, set_snapshot_version

def clear_snapshots():
    global _snapshots
    _snapshots = {}


def get_snapshot(user_id):
    return _snapshots.get(user_id)


def refresh_snapshot(user_id, profile):
    existing = _snapshots.get(user_id)
    incoming_version = profile["version"]

    if existing is not None:
        existing_snapshot_version = get_snapshot_version(user_id)
        cache_version = get_cache_version(user_id)

        if existing_snapshot_version >= cache_version:
            return existing

    _snapshots[user_id] = {
        "user_id": user_id,
        "display_name": profile["display_name"],
        "version": incoming_version,
    }
    set_snapshot_version(user_id, incoming_version)
    return _snapshots[user_id]
