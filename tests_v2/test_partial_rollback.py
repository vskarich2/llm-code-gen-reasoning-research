"""Tests for partial_rollback family (partial_state_update).

Invariant: if a multi-step operation fails mid-sequence,
           all prior steps must be compensated (rolled back).
"""


def test_a(mod):
    """Level A: failed charge must release inventory reservation."""
    inv = mod.Inventory(10)
    wallet = mod.Wallet(0)  # zero balance — charge will fail

    try:
        mod.place_order(inv, wallet, 3, 10.0)
    except ValueError:
        pass  # expected: insufficient funds

    avail = inv.available()
    if avail != 10:
        return False, [
            f"inventory available={avail} after failed order, expected 10 "
            f"(reservation not rolled back)"
        ]

    if inv.reserved != 0:
        return False, [
            f"inventory reserved={inv.reserved} after failed order, expected 0"
        ]

    return True, ["inventory correctly released after payment failure"]


def test_b(mod):
    """Level B: failed payment must release inventory reservation."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_stock"):
        mod._stock = {}
    if hasattr(mod, "_reserved"):
        mod._reserved = {}
    if hasattr(mod, "_notifications"):
        mod._notifications = []
    if hasattr(mod, "_gateway_fail"):
        mod._gateway_fail = False

    mod.add_product("SKU-100", 10)
    mod.set_gateway_fail(True)

    try:
        mod.place_order("SKU-100", 3, 25.0)
    except ValueError:
        pass  # expected: payment declined

    avail = mod.available("SKU-100")
    if avail != 10:
        return False, [
            f"available={avail} after failed payment, expected 10 "
            f"(reservation not rolled back)"
        ]

    reserved = mod.get_reserved("SKU-100")
    if reserved != 0:
        return False, [
            f"reserved={reserved} after failed payment, expected 0"
        ]

    return True, ["inventory released after payment gateway failure"]


def test_c(mod):
    """Level C: failed payment must release inventory AND clean reasoning_evaluator_audit log."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_stock"):
        mod._stock = {}
    if hasattr(mod, "_reserved"):
        mod._reserved = {}
    if hasattr(mod, "_audit_log"):
        mod._audit_log = []
    if hasattr(mod, "_notifications"):
        mod._notifications = []
    if hasattr(mod, "_gateway_fail"):
        mod._gateway_fail = False

    mod.add_product("WIDGET-1", 20)
    mod.set_gateway_fail(True)

    try:
        mod.place_order("WIDGET-1", 5, 10.0)
    except ValueError:
        pass  # expected: payment declined

    # Check inventory rolled back
    avail = mod.available("WIDGET-1")
    if avail != 20:
        return False, [
            f"available={avail} after failed payment, expected 20 "
            f"(reservation not rolled back)"
        ]

    # Check reasoning_evaluator_audit log cleaned
    audit = mod.get_audit_log()
    if len(audit) != 0:
        return False, [
            f"audit_log has {len(audit)} entries after failed order, expected 0 "
            f"(reasoning_evaluator_audit entry not removed on rollback)"
        ]

    return True, ["inventory released and reasoning_evaluator_audit log cleaned after payment failure"]
