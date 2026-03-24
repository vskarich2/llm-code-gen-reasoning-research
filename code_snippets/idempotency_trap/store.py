_records = {}
_apply_log = []


def upsert(key, value):
    _records[key] = value


def get(key):
    return _records.get(key)


def apply_delta(key, delta):
    current = _records.get(key, 0)
    _records[key] = current + delta
    _apply_log.append({"key": key, "delta": delta, "new": current + delta})


def get_apply_log():
    return list(_apply_log)


def clear():
    _records.clear()
    _apply_log.clear()
