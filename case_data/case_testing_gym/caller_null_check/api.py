_records = {
    "u1": {"id": "u1", "name": "Alice", "active": True},
    "u2": {"id": "u2", "name": "Bob", "active": True},
    "u3": {"id": "u3", "name": "Carol", "active": False},
}


def get_record(record_id):
    # BUG: returns None on not-found instead of raising NotFoundError.
    # The API contract (verified by tests) requires an exception on not-found
    # so callers can distinguish "not found" from "found but empty/None".
    return _records.get(record_id)


def list_active():
    return [r for r in _records.values() if r.get("active")]


def count_records():
    return len(_records)


def reset():
    global _records
    _records = {
        "u1": {"id": "u1", "name": "Alice", "active": True},
        "u2": {"id": "u2", "name": "Bob", "active": True},
        "u3": {"id": "u3", "name": "Carol", "active": False},
    }
