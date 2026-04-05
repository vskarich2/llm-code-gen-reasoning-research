"""User service — orchestrates reads and writes across layers."""

from snapshot_store import get_snapshot, refresh_snapshot
from cache_layer import get_cached, set_cached, invalidate
from user_repo import get_profile, update_display_name, create_user


def read_user(user_id):
    """Read user profile. Priority: snapshot > cache > repo."""
    # 1. Snapshot (fastest, preferred for warm reads)
    snap = get_snapshot(user_id)
    if snap is not None:
        return snap

    # 2. Cache
    cached = get_cached(user_id)
    if cached is not None:
        return cached

    # 3. Repository (authoritative, slowest)
    profile = get_profile(user_id)
    if profile is not None:
        set_cached(user_id, profile)
        refresh_snapshot(user_id, profile)
    return profile


def rename_user(user_id, new_name):
    """Rename a user. Invalidates cache and refreshes snapshot."""
    profile = update_display_name(user_id, new_name)

    # Invalidate cache (removes data, but version index persists)
    invalidate(user_id)

    # Refresh snapshot with new profile from repo
    refresh_snapshot(user_id, profile)

    return profile
