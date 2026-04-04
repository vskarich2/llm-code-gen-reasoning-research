"""Tests for partial_rollback family (partial_state_update).

Invariant: multi-step operations must compensate all prior steps on failure.
           BOTH the happy path (successful order) AND failure path (rollback)
           must be tested. A no-op place_order must fail.

Equivalence policy: behavior_plus_compensation_semantics
Mechanism evidence: EXERCISE
Strength: STRONG (V2.1 — was WEAK, added happy path + no-op exclusion)

V2.1: no-op place_order now correctly FAILS (happy path verifies
      successful orders actually reduce inventory).
"""


def _reset_state(mod):
    """Reset module state for levels B and C."""
    if hasattr(mod, "reset"):
        mod.reset()
    for attr in ("_stock", "_reserved", "_audit_log", "_notifications"):
        val = getattr(mod, attr, None)
        if isinstance(val, dict):
            val.clear()
        elif isinstance(val, list):
            val.clear()
    if hasattr(mod, "_gateway_fail"):
        mod._gateway_fail = False


def test_a(mod):
    """Level A: happy path works AND failed charge releases reservation."""
    errors = []

    # --- HAPPY PATH: successful order must reduce inventory ---
    inv_ok = mod.Inventory(10)
    wallet_ok = mod.Wallet(100)  # sufficient funds
    try:
        mod.place_order(inv_ok, wallet_ok, 3, 10.0)
    except Exception as e:
        return False, [f"happy path raised unexpectedly: {e}"]

    if inv_ok.available() != 7:
        errors.append(
            f"happy path: available={inv_ok.available()}, expected 7 "
            f"(order should reduce inventory)"
        )

    # --- FAILURE PATH: failed charge must release reservation ---
    inv = mod.Inventory(10)
    wallet = mod.Wallet(0)  # zero balance — charge will fail

    raised = False
    try:
        mod.place_order(inv, wallet, 3, 10.0)
    except ValueError:
        raised = True

    if not raised:
        errors.append("failure path: place_order did not raise ValueError")

    if inv.available() != 10:
        errors.append(
            f"failure path: available={inv.available()}, expected 10 "
            f"(reservation not rolled back)"
        )
    if inv.reserved != 0:
        errors.append(f"failure path: reserved={inv.reserved}, expected 0")

    if errors:
        return False, errors
    return True, ["happy path reduces inventory, failure path rolls back"]


def test_b(mod):
    """Level B: happy path works AND failed payment releases reservation."""
    _reset_state(mod)
    errors = []

    # --- HAPPY PATH ---
    mod.add_product("SKU-100", 10)
    mod.set_gateway_fail(False)
    try:
        mod.place_order("SKU-100", 3, 25.0)
    except Exception as e:
        return False, [f"happy path raised unexpectedly: {e}"]

    if mod.available("SKU-100") != 7:
        errors.append(
            f"happy path: available={mod.available('SKU-100')}, expected 7"
        )

    # --- FAILURE PATH ---
    _reset_state(mod)
    mod.add_product("SKU-100", 10)
    mod.set_gateway_fail(True)

    raised = False
    try:
        mod.place_order("SKU-100", 3, 25.0)
    except ValueError:
        raised = True

    if not raised:
        errors.append("failure path: place_order did not raise ValueError")

    if mod.available("SKU-100") != 10:
        errors.append(
            f"failure path: available={mod.available('SKU-100')}, expected 10"
        )
    if mod.get_reserved("SKU-100") != 0:
        errors.append(
            f"failure path: reserved={mod.get_reserved('SKU-100')}, expected 0"
        )

    if errors:
        return False, errors
    return True, ["happy path works, failure path rolls back"]


def test_c(mod):
    """Level C: happy path works AND failure rolls back inventory+audit."""
    _reset_state(mod)
    errors = []

    # --- HAPPY PATH ---
    mod.add_product("WIDGET-1", 20)
    mod.set_gateway_fail(False)
    try:
        mod.place_order("WIDGET-1", 5, 10.0)
    except Exception as e:
        return False, [f"happy path raised unexpectedly: {e}"]

    if mod.available("WIDGET-1") != 15:
        errors.append(
            f"happy path: available={mod.available('WIDGET-1')}, expected 15"
        )
    hp_audit = mod.get_audit_log()
    if len(hp_audit) != 1:
        errors.append(
            f"happy path: audit_log has {len(hp_audit)} entries, expected 1"
        )

    # --- FAILURE PATH ---
    _reset_state(mod)
    mod.add_product("WIDGET-1", 20)
    mod.set_gateway_fail(True)

    raised = False
    try:
        mod.place_order("WIDGET-1", 5, 10.0)
    except ValueError:
        raised = True

    if not raised:
        errors.append("failure path: place_order did not raise ValueError")

    if mod.available("WIDGET-1") != 20:
        errors.append(
            f"failure path: available={mod.available('WIDGET-1')}, expected 20"
        )
    fail_audit = mod.get_audit_log()
    if len(fail_audit) != 0:
        errors.append(
            f"failure path: audit_log has {len(fail_audit)} entries, "
            f"expected 0 (audit not cleaned on rollback)"
        )

    if errors:
        return False, errors
    return True, ["happy path works+audits, failure rolls back inventory+audit"]
