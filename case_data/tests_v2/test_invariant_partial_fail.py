"""Test for invariant_partial_fail: balance conservation on transfer failure.

Invariant: (1) successful transfer moves funds correctly, AND
           (2) failed transfer conserves total balance via rollback.
           A no-op execute_transfer that does nothing must FAIL.

Equivalence policy: behavior_plus_compensation_semantics
Mechanism evidence: EXERCISE
Strength: STRONG (V2.1 — was WEAK, added happy path + no-op exclusion)

V2.1: no-op execute_transfer now correctly FAILS because happy path
      requires sender.balance to change after successful transfer.
"""

import random as _random_mod


def test(mod):
    entries = getattr(mod, "_entries", None)
    if isinstance(entries, list):
        entries.clear()
    alerts = getattr(mod, "_alerts", None)
    if isinstance(alerts, list):
        alerts.clear()

    Account = getattr(mod, "Account", None)
    execute_transfer = getattr(mod, "execute_transfer", None)
    if not all([Account, execute_transfer]):
        return False, ["missing Account or execute_transfer"]

    errors = []
    original_random = _random_mod.random
    mod_random = getattr(mod, "random", None)

    def _patch_random(val):
        _random_mod.random = lambda: val
        if mod_random is not None and hasattr(mod_random, "random"):
            mod_random.random = lambda: val

    def _restore_random():
        _random_mod.random = original_random
        if mod_random is not None and hasattr(mod_random, "random"):
            mod_random.random = original_random

    # --- HAPPY PATH: successful transfer must move funds ---
    try:
        _patch_random(0.99)  # above 0.3 threshold — no failure
        sender_ok = Account("s_ok", 100)
        receiver_ok = Account("r_ok", 0)

        try:
            execute_transfer(sender_ok, receiver_ok, 50)
        except RuntimeError:
            errors.append(
                "happy path: execute_transfer raised RuntimeError "
                "with random=0.99 (should succeed)"
            )

        if sender_ok.balance != 50:
            errors.append(
                f"happy path: sender.balance={sender_ok.balance}, "
                f"expected 50 (transfer should debit sender)"
            )
        if receiver_ok.balance != 50:
            errors.append(
                f"happy path: receiver.balance={receiver_ok.balance}, "
                f"expected 50 (transfer should credit receiver)"
            )
        hp_total = sender_ok.balance + receiver_ok.balance
        if hp_total != 100:
            errors.append(
                f"happy path: total={hp_total}, expected 100 (conservation)"
            )
    finally:
        _restore_random()

    # --- FAILURE PATH: failed transfer must conserve balance ---
    # Reset module-level state for second run
    entries2 = getattr(mod, "_entries", None)
    if isinstance(entries2, list):
        entries2.clear()
    alerts2 = getattr(mod, "_alerts", None)
    if isinstance(alerts2, list):
        alerts2.clear()

    try:
        _patch_random(0.0)  # below 0.3 — triggers failure
        sender = Account("s1", 100)
        receiver = Account("r1", 0)
        initial_total = sender.balance + receiver.balance

        raised = False
        try:
            execute_transfer(sender, receiver, 50)
        except RuntimeError:
            raised = True
        except Exception as e:
            errors.append(f"failure path: unexpected {type(e).__name__}: {e}")

        if not raised:
            errors.append(
                "failure path: execute_transfer did not raise RuntimeError "
                "with random=0.0 (should trigger transient failure)"
            )

        final_total = sender.balance + receiver.balance
        if final_total != initial_total:
            errors.append(
                f"failure path: total={final_total}, expected={initial_total}"
                f" (sender={sender.balance}, receiver={receiver.balance})"
            )
    finally:
        _restore_random()

    # --- ANTI-HARDCODING: different amount ---
    try:
        _patch_random(0.99)
        sender_2 = Account("s2", 200)
        receiver_2 = Account("r2", 50)
        try:
            execute_transfer(sender_2, receiver_2, 75)
        except RuntimeError:
            errors.append("anti-hardcoding: raised with random=0.99")

        if sender_2.balance != 125:
            errors.append(
                f"anti-hardcoding: sender.balance={sender_2.balance}, "
                f"expected 125"
            )
        if receiver_2.balance != 125:
            errors.append(
                f"anti-hardcoding: receiver.balance={receiver_2.balance}, "
                f"expected 125"
            )
    finally:
        _restore_random()

    if errors:
        return False, errors
    return True, [
        "happy path moves funds, failure path conserves, anti-hardcoding ok"
    ]
