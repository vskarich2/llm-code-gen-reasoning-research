"""Test for lost_update: both sequential and interleaved must produce value=2."""


def test(mod):
    seq = mod.sequential_double_increment()
    if seq != 2:
        return False, [f"sequential: expected 2, got {seq}"]

    interleaved = mod.interleaved_double_increment()
    if interleaved != 2:
        return False, [f"interleaved: expected 2, got {interleaved}"]

    return True, ["both sequential and interleaved produce correct count"]
