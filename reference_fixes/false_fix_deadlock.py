"""Resource transfers with atomic lock acquisition — fixes deadlock."""

_locks = {}
_state = {"A": 100, "B": 100}


def reset():
    _locks.clear()
    _state["A"] = 100
    _state["B"] = 100


def acquire(resource):
    if _locks.get(resource):
        raise RuntimeError(f"deadlock: {resource} already locked")
    _locks[resource] = True


def release(resource):
    _locks[resource] = False


def get_state():
    return dict(_state)


def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results


def make_transfer_a_to_b_steps(amount):
    """FIX: entire transfer is a single atomic step (both locks + transfer)."""

    def step_atomic_transfer():
        acquire("A")
        acquire("B")
        _state["A"] -= amount
        _state["B"] += amount
        release("B")
        release("A")
        return "transferred_a_to_b"

    def step_noop():
        return "noop"

    return step_atomic_transfer, step_noop


def make_transfer_b_to_a_steps(amount):
    """FIX: entire transfer is a single atomic step, canonical order A then B."""

    def step_atomic_transfer():
        acquire("A")  # canonical order: A first
        acquire("B")
        _state["B"] -= amount
        _state["A"] += amount
        release("B")
        release("A")
        return "transferred_b_to_a"

    def step_noop():
        return "noop"

    return step_atomic_transfer, step_noop


def sequential_transfers():
    reset()
    lock_ab, do_ab = make_transfer_a_to_b_steps(10)
    lock_ba, do_ba = make_transfer_b_to_a_steps(10)
    run_steps([
        (lock_ab, ()), (do_ab, ()),
        (lock_ba, ()), (do_ba, ()),
    ])
    return get_state()


def interleaved_transfers():
    reset()
    lock_ab, do_ab = make_transfer_a_to_b_steps(10)
    lock_ba, do_ba = make_transfer_b_to_a_steps(10)
    try:
        run_steps([
            (lock_ab, ()),
            (lock_ba, ()),
            (do_ab, ()),
            (do_ba, ()),
        ])
        return get_state()
    except RuntimeError as e:
        return {"error": str(e)}
