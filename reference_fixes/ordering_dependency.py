"""Pipeline with auto-init — fixes ordering dependency."""

_log = []
_initialized = False
_buffer = []


def reset():
    global _initialized
    _log.clear()
    _buffer.clear()
    _initialized = False


def init():
    global _initialized
    _initialized = True
    _log.append("init")
    # FIX: drain buffer of any items that arrived before init
    for item in _buffer:
        _log.append(f"processed:{item}")
    _buffer.clear()


def process(item):
    """FIX: if not initialized, buffer the item for later processing."""
    if not _initialized:
        _buffer.append(item)
        return True  # buffered, not lost
    _log.append(f"processed:{item}")
    return True


def shutdown():
    _log.append("shutdown")
    return list(_log)


def get_log():
    return list(_log)


def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results


def correct_order():
    reset()
    run_steps([
        (init, ()),
        (process, ("a",)),
        (process, ("b",)),
        (shutdown, ()),
    ])
    return get_log()


def broken_order():
    reset()
    run_steps([
        (process, ("a",)),
        (init, ()),
        (process, ("b",)),
        (shutdown, ()),
    ])
    return get_log()
