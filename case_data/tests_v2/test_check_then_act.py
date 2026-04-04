"""Test for check_then_act: balance must never go negative."""


def test(mod):
    seq = mod.sequential_withdrawals()
    if seq != 20:
        return False, [f"sequential: expected balance=20, got {seq}"]

    interleaved = mod.interleaved_withdrawals()
    if interleaved < 0:
        return False, [f"interleaved: balance went negative ({interleaved})"]
    if interleaved != 20:
        return False, [f"interleaved: expected balance=20, got {interleaved}"]

    # Anti-hardcoding: different starting balance and amounts
    for fn in ("reset", "create_account", "get_balance",
               "make_withdraw_steps", "run_steps"):
        if not hasattr(mod, fn):
            return False, [f"model removed {fn}() — structural check failed"]

    mod.reset()
    mod.create_account("bob", 200)
    check_a, act_a = mod.make_withdraw_steps("bob", 150)
    check_b, act_b = mod.make_withdraw_steps("bob", 150)
    mod.run_steps([(check_a, ()), (act_a, ()), (check_b, ()), (act_b, ())])
    bal = mod.get_balance("bob")
    if bal != 50:
        return False, [f"anti-hardcoding: expected balance=50, got {bal}"]

    return True, ["balance correct under all interleavings, anti-hardcoding passed"]
