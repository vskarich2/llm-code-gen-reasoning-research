"""Test for lost_update: both sequential and interleaved must produce value=2.

Bug: concurrent increments read the same initial value and write back the same
     result, losing one update.

Invariants:
1. Trap-catching: sequential double increment → 2
2. Trap-catching: interleaved double increment → 2
3. Generalization: anti-hardcoding with different start value
4. Generalization: triple increment must also work
5. Causal-location: structural check — key functions must exist
"""


def test(mod):
    errors = []

    # ── Invariant 1: Sequential double increment ──
    seq = mod.sequential_double_increment()
    if seq != 2:
        errors.append(f"sequential: expected 2, got {seq}")

    # ── Invariant 2: Interleaved double increment ──
    interleaved = mod.interleaved_double_increment()
    if interleaved != 2:
        errors.append(f"interleaved: expected 2, got {interleaved}")

    # ── Invariant 3: Anti-hardcoding with different start value ──
    for fn in ("reset", "get", "_set", "make_increment_steps", "run_steps"):
        if not hasattr(mod, fn):
            errors.append(f"structural: {fn}() not found")
            return False, errors

    mod.reset()
    mod._set(10)
    read_a, write_a = mod.make_increment_steps()
    read_b, write_b = mod.make_increment_steps()
    mod.run_steps([(read_a, ()), (write_a, ()), (read_b, ()), (write_b, ())])
    val = mod.get()
    if val != 12:
        errors.append(f"anti-hardcoding: start=10, two increments should give 12, got {val}")

    # ── Invariant 4: Generalization — triple increment ──
    mod.reset()
    mod._set(0)
    steps = []
    for _ in range(3):
        r, w = mod.make_increment_steps()
        steps.extend([(r, ()), (w, ())])
    mod.run_steps(steps)
    val3 = mod.get()
    if val3 != 3:
        errors.append(
            f"generalization: start=0, three sequential increments should give 3, got {val3}"
        )

    # ── Invariant 5: Interleaved triple (all reads then all writes) ──
    mod.reset()
    mod._set(0)
    reads = []
    writes = []
    for _ in range(3):
        r, w = mod.make_increment_steps()
        reads.append((r, ()))
        writes.append((w, ()))
    # All reads first, then all writes — maximally interleaved
    mod.run_steps(reads + writes)
    val_interleaved3 = mod.get()
    if val_interleaved3 != 3:
        errors.append(
            f"generalization: interleaved 3 increments should give 3, got {val_interleaved3}"
        )

    if errors:
        return False, errors
    return True, [
        "sequential correct", "interleaved correct",
        "anti-hardcoding passed", "triple increment works",
    ]
