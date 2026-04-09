

from snapshot_store import get_snapshot, refresh_snapshot
from cache_layer import get_cached, set_cached, invalidate
from user_repo import get_profile, update_display_name, create_user

def read_user(user_id):

    snap = get_snapshot(user_id)
    if snap is not None:
        return snap

    cached = get_cached(user_id)
    if cached is not None:
        return cached

    profile = get_profile(user_id)
    if profile is not None:
        set_cached(user_id, profile)
        refresh_snapshot(user_id, profile)
    return profile

def rename_user(user_id, new_name):
    profile = update_display_name(user_id, new_name)
    invalidate(user_id)
    refresh_snapshot(user_id, profile)

    return profile
