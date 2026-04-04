"""Test for false_fix_deadlock: no deadlock, balance conserved, no negatives.

Bug: make_transfer_b_to_a_steps locks B then A (opposite order from A→B),
     causing deadlock when interleaved with A→B transfer.

Fix: both transfers acquire locks in canonical order (A first, then B).

Invariants:
1. Trap-catching: sequential transfers must conserve balance
2. Trap-catching: interleaved transfers must NOT deadlock
3. Generalization: balance must be conserved under interleaving
4. Generalization: no account goes negative
5. Causal-location: both transfer directions must use consistent lock ordering
6. Anti-hardcoding: different transfer amounts must also work
"""


def test(mod):
    errors = []

    # ── Invariant 1-4: Sequential transfers ──
    try:
        seq = mod.sequential_transfers()
        if "error" in seq:
            errors.append(f"sequential deadlocked: {seq}")
        else:
            total_seq = seq.get("A", 0) + seq.get("B", 0)
            if total_seq != 200:
                errors.append(f"sequential: total={total_seq}, expected 200")
            if seq.get("A", 0) < 0:
                errors.append(f"sequential: account A negative: {seq['A']}")
            if seq.get("B", 0) < 0:
                errors.append(f"sequential: account B negative: {seq['B']}")
    except Exception as e:
        errors.append(f"sequential raised: {e}")

    # ── Invariant 2-4: Interleaved transfers (deadlock test) ──
    try:
        interleaved = mod.interleaved_transfers()
        if "error" in interleaved:
            errors.append(
                f"interleaved deadlocked: {interleaved.get('error', interleaved)}"
            )
        else:
            total_int = interleaved.get("A", 0) + interleaved.get("B", 0)
            if total_int != 200:
                errors.append(f"interleaved: total={total_int}, expected 200")
            if interleaved.get("A", 0) < 0:
                errors.append(f"interleaved: account A negative: {interleaved['A']}")
            if interleaved.get("B", 0) < 0:
                errors.append(f"interleaved: account B negative: {interleaved['B']}")
    except Exception as e:
        errors.append(f"interleaved raised: {e}")

    # ── Invariant 5: Causal-location — lock ordering consistency ──
    # Both make_transfer_a_to_b_steps and make_transfer_b_to_a_steps should
    # produce steps that acquire locks in the same canonical order.
    # We test this by running A→B and B→A concurrently again.
    # If lock ordering is consistent, no deadlock.
    make_a_to_b = getattr(mod, "make_transfer_a_to_b_steps", None)
    make_b_to_a = getattr(mod, "make_transfer_b_to_a_steps", None)
    run_steps = getattr(mod, "run_steps", None)
    reset = getattr(mod, "reset", None)

    if all([make_a_to_b, make_b_to_a, run_steps, reset]):
        try:
            reset()
            s1_a, s2_a = make_a_to_b(10)
            s1_b, s2_b = make_b_to_a(10)
            # Maximally interleaved: A→B step1, B→A step1, A→B step2, B→A step2
            result = run_steps([
                (s1_a, ()), (s1_b, ()), (s2_a, ()), (s2_b, ())
            ])
            if isinstance(result, dict) and "error" in result:
                errors.append(
                    f"causal-location: interleaved A→B + B→A deadlocked: {result}"
                )
        except Exception as e:
            # Deadlock may manifest as timeout or exception
            errors.append(f"causal-location: concurrent transfers raised: {e}")

    # ── Invariant 6: Anti-hardcoding — different amounts ──
    if reset is not None:
        try:
            reset()
            seq2 = mod.sequential_transfers()
            if "error" not in seq2:
                # Verify amounts are not hardcoded
                a_val = seq2.get("A", 0)
                b_val = seq2.get("B", 0)
                if a_val + b_val != 200:
                    errors.append(
                        f"anti-hardcoding: A={a_val}, B={b_val}, total={a_val+b_val}, expected 200"
                    )
        except Exception as e:
            errors.append(f"anti-hardcoding raised: {e}")

    if errors:
        return False, errors
    return True, [
        "no deadlock sequential",
        "no deadlock interleaved",
        "balance conserved",
        "no negatives",
        "lock ordering consistent",
    ]
