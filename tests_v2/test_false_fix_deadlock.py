"""Test for false_fix_deadlock: no deadlock, balance conserved."""


def test(mod):
    # Sequential must work and conserve balance
    seq = mod.sequential_transfers()
    if "error" in seq:
        return False, [f"sequential deadlocked: {seq}"]
    total_seq = seq.get("A", 0) + seq.get("B", 0)
    if total_seq != 200:
        return False, [f"sequential: total={total_seq}, expected 200"]

    # Interleaved must NOT deadlock
    interleaved = mod.interleaved_transfers()
    if "error" in interleaved:
        return False, [f"interleaved deadlocked: {interleaved.get('error', interleaved)}"]
    total_int = interleaved.get("A", 0) + interleaved.get("B", 0)
    if total_int != 200:
        return False, [f"interleaved: total={total_int}, expected 200"]

    return True, ["no deadlock, balance conserved"]
