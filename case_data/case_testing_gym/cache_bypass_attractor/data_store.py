_access_count = 0
_data = {
    "key_a": "value_a",
    "key_b": "value_b",
    "key_c": "value_c",
    "key_d": "value_d",
}


def fetch(key):
    global _access_count
    _access_count += 1
    return _data.get(key)


def get_access_count():
    return _access_count


def reset_access_count():
    global _access_count
    _access_count = 0


def reset():
    global _access_count
    _access_count = 0
