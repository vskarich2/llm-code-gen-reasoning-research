from store import write

_counter = 0


def write_fresh(key, compute_fn):
    """Compute value fresh and write with version tracking."""
    global _counter
    _counter += 1
    value = compute_fn()
    write(key, value, version=_counter)
    return value


def reset():
    global _counter
    _counter = 0
