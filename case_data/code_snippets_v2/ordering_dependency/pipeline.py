

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


def process(item):
    if not _initialized:
        _log.append(f"error:not_init:{item}")
        return False
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
