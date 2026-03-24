_log = []


def update_value(store, key, value):
    store[key] = value
    _log.append({"key": key, "value": value})


def get_log():
    return list(_log)


def clear():
    _log.clear()
