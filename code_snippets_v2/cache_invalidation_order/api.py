from service import update_record, read_record, safe_update


def put(key, value):
    update_record(key, value)
    return read_record(key)


def get(key):
    return read_record(key)


def safe_put(key, value):
    safe_update(key, value)
    return read_record(key)
