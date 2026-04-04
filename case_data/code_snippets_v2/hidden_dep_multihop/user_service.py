from user_repo import persist_user, remove_user, sync_user_to_db, lookup_user
from cache_writer import cache_delete, refresh_user_snapshot, sync_user_to_cache


def save_user(user):
    persist_user(user)
    refresh_user_snapshot(user)


def delete_user(user_id):
    remove_user(user_id)
    cache_delete(f"user:{user_id}")


def rename_user(user_id, new_name):
    from user_repo import db
    db.update_name(user_id, new_name)
    updated = lookup_user(user_id)
    if updated:
        refresh_user_snapshot(updated)


def bulk_warm_cache(users):
    for u in users:
        refresh_user_snapshot(u)


def migrate_legacy_user(legacy_record):
    converted = {"id": legacy_record["uid"], "name": legacy_record["full_name"]}
    sync_user_to_db(converted)
