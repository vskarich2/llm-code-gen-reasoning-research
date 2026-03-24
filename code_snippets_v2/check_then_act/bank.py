"""Bank with non-atomic check-then-act withdrawal, simulated via steps."""

_accounts = {}


def reset():
    _accounts.clear()


def create_account(name, balance):
    _accounts[name] = balance


def get_balance(name):
    return _accounts.get(name, 0)


def check_balance(name, amount):
    """CHECK: is balance sufficient?"""
    return _accounts.get(name, 0) >= amount


def do_withdraw(name, amount):
    """ACT: decrement balance. Assumes caller verified."""
    _accounts[name] = _accounts.get(name, 0) - amount


def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results


def make_withdraw_steps(name, amount):
    """Split withdrawal into separate check and act steps.

    BUG: under interleaving, both checks pass before either debits.
    """
    result = {"approved": False}

    def step_check():
        result["approved"] = check_balance(name, amount)
        return ("check", result["approved"])

    def step_act():
        if result["approved"]:
            do_withdraw(name, amount)
        return ("act", result["approved"])

    return step_check, step_act


def sequential_withdrawals():
    """Two withdrawals of 80 from balance=100. Sequential: second denied."""
    reset()
    create_account("alice", 100)
    check_a, act_a = make_withdraw_steps("alice", 80)
    check_b, act_b = make_withdraw_steps("alice", 80)
    run_steps([(check_a, ()), (act_a, ()), (check_b, ()), (act_b, ())])
    return get_balance("alice")


def interleaved_withdrawals():
    """Two withdrawals of 80, interleaved: BUG — both approved, overdraft."""
    reset()
    create_account("alice", 100)
    check_a, act_a = make_withdraw_steps("alice", 80)
    check_b, act_b = make_withdraw_steps("alice", 80)
    run_steps([(check_a, ()), (check_b, ()), (act_a, ()), (act_b, ())])
    return get_balance("alice")
