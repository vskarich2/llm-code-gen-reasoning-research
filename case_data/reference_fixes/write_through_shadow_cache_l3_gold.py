"""Reference fix: use repo version as freshness authority in refresh_snapshot."""

_snapshots = {}

from user_repo import get_repo_version
from version_index import get_snapshot_version, set_snapshot_version


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
        repo_version = get_repo_version(user_id)

        # FIX: use repository as freshness authority
        if existing_snapshot_version >= repo_version and existing_snapshot_version >= incoming_version:
            return existing

    _snapshots[user_id] = {
        "user_id": user_id,
        "display_name": profile["display_name"],
        "version": incoming_version,
    }
    set_snapshot_version(user_id, incoming_version)
    return _snapshots[user_id]
