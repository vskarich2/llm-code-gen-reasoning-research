import random
from store import insert, exists


def write_record(key, value):
    if random.random() < 0.3:
        raise ConnectionError("transient write failure")
    return insert(key, value)


def safe_write(key, value):
    if exists(key):
        return get(key)
    return insert(key, value)


def write_with_retry(key, value, max_retries=3):
    for attempt in range(max_retries):
        try:
            return write_record(key, value)
        except ConnectionError:
            continue
    raise ConnectionError(f"failed after {max_retries} retries")
