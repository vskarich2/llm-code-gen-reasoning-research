from search_index import reindex

_db = {}


def create(user_id, name, email):
    import time
    now = time.time()
    _db[user_id] = {
        "user_id": user_id,
        "name": name,
        "email": email,
        "created_at": now,
        "modified_at": now,
    }
    reindex(user_id, name)
    return _db[user_id]


def update(user_id, new_name):
    if user_id not in _db:
        raise KeyError(f"user {user_id} not found")
    # BUG: updates name but forgets to update modified_at and search index
    _db[user_id]["name"] = new_name
    return _db[user_id]


def get(user_id):
    return _db.get(user_id)


def get_modified_at(user_id):
    rec = _db.get(user_id)
    if rec is None:
        return None
    return rec["modified_at"]


def reset():
    _db.clear()
