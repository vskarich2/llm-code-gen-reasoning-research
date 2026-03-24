"""Bank with atomic check-then-act — fixes overdraft under interleaving."""

_accounts = {}


def reset():
    _accounts.clear()


def create_account(name, balance):
    _accounts[name] = balance


def get_balance(name):
    return _accounts.get(name, 0)


def check_balance(name, amount):
    return _accounts.get(name, 0) >= amount


def do_withdraw(name, amount):
    _accounts[name] = _accounts.get(name, 0) - amount


def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results


def make_withdraw_steps(name, amount):
    """FIX: check+act combined into a single atomic step.

    The act re-checks balance before debiting, preventing overdraft
    even under interleaving.
    """
    result = {"approved": False}

    def step_check_and_act():
        """Atomic check-then-act: re-verify balance at debit time."""
        if check_balance(name, amount):
            do_withdraw(name, amount)
            result["approved"] = True
        else:
            result["approved"] = False
        return ("check_and_act", result["approved"])

    def step_noop():
        return ("noop",)

    return step_check_and_act, step_noop


def sequential_withdrawals():
    reset()
    create_account("alice", 100)
    check_a, act_a = make_withdraw_steps("alice", 80)
    check_b, act_b = make_withdraw_steps("alice", 80)
    run_steps([(check_a, ()), (act_a, ()), (check_b, ()), (act_b, ())])
    return get_balance("alice")


def interleaved_withdrawals():
    reset()
    create_account("alice", 100)
    check_a, act_a = make_withdraw_steps("alice", 80)
    check_b, act_b = make_withdraw_steps("alice", 80)
    run_steps([(check_a, ()), (check_b, ()), (act_a, ()), (act_b, ())])
    return get_balance("alice")
