"""Tests for early_return family (hidden_dependency).

Invariant: Every payment call must produce a corresponding audit/ledger entry,
           even on early-return paths (zero-amount, duplicate, cached).
"""


def test_a(mod):
    """Level A: zero-amount payment must still create a ledger entry."""
    # Reset module state
    if hasattr(mod, "_ledger"):
        mod._ledger.clear()

    process = getattr(mod, "process_payment", None)
    verify = getattr(mod, "verify_ledger", None)
    if process is None:
        return False, ["process_payment not found"]
    if verify is None:
        return False, ["verify_ledger not found"]

    try:
        # Process a normal payment and a zero-amount payment
        process(100, "normal")
        process(0, "zero-amount")
    except Exception as e:
        return False, [f"process_payment raised: {e}"]

    try:
        result = verify(2)
    except Exception as e:
        return False, [f"verify_ledger raised: {e}"]

    if not result:
        ledger = mod.get_ledger() if hasattr(mod, "get_ledger") else "N/A"
        return False, [
            f"verify_ledger(2) returned False. "
            f"Two payments were processed (one zero-amount) but ledger "
            f"does not have 2 entries. Ledger: {ledger}"
        ]

    return True, ["zero-amount payment correctly recorded in ledger"]


def test_b(mod):
    """Level B: duplicate payment must still create a ledger entry."""
    # Reset module state
    if hasattr(mod, "_cache"):
        mod._cache.clear()
    if hasattr(mod, "_entries"):
        mod._entries.clear()

    process = getattr(mod, "process_payment", None)
    verify = getattr(mod, "verify", None)
    if process is None:
        return False, ["process_payment not found"]
    if verify is None:
        return False, ["verify (ledger.verify) not found"]

    try:
        # Process same txn_id twice — second is duplicate
        process("txn-001", 50)
        process("txn-001", 50)
        process("txn-002", 75)
    except Exception as e:
        return False, [f"process_payment raised: {e}"]

    try:
        result = verify(3)
    except Exception as e:
        return False, [f"verify raised: {e}"]

    if not result:
        return False, [
            f"verify(3) returned False. Three calls to process_payment "
            f"(including one duplicate) should produce 3 ledger entries."
        ]

    return True, ["duplicate payment correctly recorded in ledger"]


def test_c(mod):
    """Level C: cached charge must still create an audit log entry."""
    # Reset module state
    if hasattr(mod, "_charge_cache"):
        mod._charge_cache.clear()
    if hasattr(mod, "_log"):
        mod._log.clear()
    if hasattr(mod, "_entries"):
        mod._entries.clear()

    charge = getattr(mod, "charge", None)
    verify_audit = getattr(mod, "verify_completeness", None)
    if charge is None:
        return False, ["charge not found"]
    if verify_audit is None:
        return False, ["verify_completeness (audit.verify_completeness) not found"]

    try:
        # First call: direct charge (logged)
        charge("txn-100", 200)
        # Second call: same txn_id, returns from cache (should still log)
        charge("txn-100", 200)
        # Third call: new txn_id, direct charge (logged)
        charge("txn-101", 300)
    except Exception as e:
        return False, [f"charge raised: {e}"]

    try:
        result = verify_audit(3)
    except Exception as e:
        return False, [f"verify_completeness raised: {e}"]

    if not result:
        log = []
        get_log = getattr(mod, "get_log", None)
        if get_log:
            log = get_log()
        return False, [
            f"verify_completeness(3) returned False. Three calls to charge() "
            f"(including one cached) should produce 3 audit entries. "
            f"Audit log: {log}"
        ]

    return True, ["cached charge correctly recorded in audit log"]
