"""Counter with atomic increment — fixes lost update under interleaving."""

_value = 0


def reset():
    global _value
    _value = 0


def get():
    return _value


def _set(v):
    global _value
    _value = v


def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results


def make_increment_steps():
    """FIX: read+write combined into a single atomic step.

    Under interleaving, each increment reads the CURRENT value
    and writes value+1 in one step — no stale read possible.
    """
    def step_atomic_increment():
        current = get()
        _set(current + 1)
        return ("atomic_increment", current + 1)

    # Return the atomic step as both "read" and "write" — only one step needed
    def step_noop():
        return ("noop",)

    return step_atomic_increment, step_noop


def sequential_double_increment():
    reset()
    read_a, write_a = make_increment_steps()
    read_b, write_b = make_increment_steps()
    run_steps([(read_a, ()), (write_a, ()), (read_b, ()), (write_b, ())])
    return get()


def interleaved_double_increment():
    reset()
    read_a, write_a = make_increment_steps()
    read_b, write_b = make_increment_steps()
    run_steps([(read_a, ()), (read_b, ()), (write_a, ()), (write_b, ())])
    return get()
