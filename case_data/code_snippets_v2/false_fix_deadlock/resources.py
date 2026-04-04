"""Resource transfers with lock-ordering deadlock, simulated via steps."""

_locks = {}
_state = {"A": 100, "B": 100}


def reset():
    _locks.clear()
    _state["A"] = 100
    _state["B"] = 100


def acquire(resource):
    """Simulate lock. Raises RuntimeError if already held (deadlock)."""
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
    """Transfer A→B: lock A first, then B."""

    def step_lock_a():
        acquire("A")
        return "locked_A"

    def step_lock_b_and_transfer():
        acquire("B")
        _state["A"] -= amount
        _state["B"] += amount
        release("B")
        release("A")
        return "transferred_a_to_b"

    return step_lock_a, step_lock_b_and_transfer


def make_transfer_b_to_a_steps(amount):
    """Transfer B→A: BUG — locks B first, then A (opposite order)."""

    def step_lock_b():
        acquire("B")
        return "locked_B"

    def step_lock_a_and_transfer():
        acquire("A")  # DEADLOCK: A is held by the other transfer
        _state["B"] -= amount
        _state["A"] += amount
        release("A")
        release("B")
        return "transferred_b_to_a"

    return step_lock_b, step_lock_a_and_transfer


def sequential_transfers():
    """A→B then B→A. Sequential: works fine."""
    reset()
    lock_ab, do_ab = make_transfer_a_to_b_steps(10)
    lock_ba, do_ba = make_transfer_b_to_a_steps(10)
    run_steps([
        (lock_ab, ()), (do_ab, ()),
        (lock_ba, ()), (do_ba, ()),
    ])
    return get_state()


def interleaved_transfers():
    """A→B and B→A interleaved: DEADLOCK."""
    reset()
    lock_ab, do_ab = make_transfer_a_to_b_steps(10)
    lock_ba, do_ba = make_transfer_b_to_a_steps(10)
    try:
        run_steps([
            (lock_ab, ()),   # A→B locks A
            (lock_ba, ()),   # B→A locks B
            (do_ab, ()),     # A→B tries to lock B — DEADLOCK
            (do_ba, ()),     # never reached
        ])
        return get_state()
    except RuntimeError as e:
        return {"error": str(e)}
