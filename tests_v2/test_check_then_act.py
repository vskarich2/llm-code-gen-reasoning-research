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

    return True, ["balance never goes negative under any interleaving"]
