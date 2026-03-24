"""Test for invariant_partial_fail: balance conservation on transfer failure.

Invariant: sender.balance + receiver.balance must be conserved after a
failed transfer. If the debit is applied but the credit fails, the debit
must be rolled back.
"""
import random as _random_mod


def test(mod):
    # Reset module-level mutable state
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

    sender = Account("s1", 100)
    receiver = Account("r1", 0)
    initial_total = sender.balance + receiver.balance

    # Patch random.random to always return 0.0 which triggers the failure
    # (0.0 < 0.3 is True)
    original_random = _random_mod.random
    try:
        _random_mod.random = lambda: 0.0
        # Also patch random in the module's namespace if it imported random
        mod_random = getattr(mod, "random", None)
        if mod_random is not None and hasattr(mod_random, "random"):
            mod_random.random = lambda: 0.0

        try:
            execute_transfer(sender, receiver, 50)
        except RuntimeError:
            pass  # Expected: transient failure
        except Exception as e:
            return False, [f"unexpected error type: {type(e).__name__}: {e}"]
    finally:
        _random_mod.random = original_random
        if mod_random is not None and hasattr(mod_random, "random"):
            mod_random.random = original_random

    final_total = sender.balance + receiver.balance

    if final_total != initial_total:
        return False, [
            f"balance not conserved: sender={sender.balance}, receiver={receiver.balance}, "
            f"total={final_total}, expected={initial_total}"
        ]

    return True, ["balance conserved after failed transfer"]
