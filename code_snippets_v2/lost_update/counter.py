"""Counter with non-atomic read-modify-write, simulated via step functions."""

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
    """Split a read-then-increment into separate read and write steps.

    BUG: under interleaving, two increments both read the same value
    and both write value+1, losing one update.
    """
    captured = {}

    def step_read():
        captured["current"] = get()
        return ("read", captured["current"])

    def step_write():
        _set(captured["current"] + 1)
        return ("write", captured["current"] + 1)

    return step_read, step_write


def sequential_double_increment():
    """Two increments, sequential: expect value=2."""
    reset()
    read_a, write_a = make_increment_steps()
    read_b, write_b = make_increment_steps()
    run_steps([(read_a, ()), (write_a, ()), (read_b, ()), (write_b, ())])
    return get()


def interleaved_double_increment():
    """Two increments, interleaved: BUG — both read 0, both write 1."""
    reset()
    read_a, write_a = make_increment_steps()
    read_b, write_b = make_increment_steps()
    run_steps([(read_a, ()), (read_b, ()), (write_a, ()), (write_b, ())])
    return get()
