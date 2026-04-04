"""Test for feature_flag_drift: use_new_pricing flag must propagate to pricing.

Bug: checkout() accepts use_new_pricing parameter but never enables/disables the
     feature flag. create_invoice always uses v1 pricing.

Fix: enable("new_pricing") before create_invoice, disable after.

Invariants:
1. Trap-catching: v2 pricing gives 10% discount on qty>=10 → total=900
2. Generalization: v1 pricing (use_new_pricing=False) must give total=1000
3. Generalization: different quantities must also apply discount correctly
4. Causal-location: flag must be cleaned up after checkout (not left enabled)
5. Anti-hardcoding: different base prices and quantities
"""


def test(mod):
    # Reset module-level mutable state
    flags = getattr(mod, "_flags", None)
    if isinstance(flags, dict):
        flags["new_pricing"] = False
        flags["v2_api"] = False
        flags["audit_mode"] = True
    invoices = getattr(mod, "_invoices", None)
    if isinstance(invoices, list):
        invoices.clear()

    checkout = getattr(mod, "checkout", None)
    if checkout is None:
        return False, ["missing checkout"]

    errors = []

    # ── Invariant 1: Trap-catching — v2 pricing with discount ──
    try:
        items1 = [{"sku": "A", "base": 100, "qty": 10}]
        invoice1 = checkout("cust1", items1, use_new_pricing=True)
        total1 = invoice1.get("total")
        if total1 != 900:
            errors.append(
                f"trap-catching: total={total1}, expected 900 "
                f"(v2 pricing: 100*10*0.9=900)"
            )
    except Exception as e:
        errors.append(f"trap-catching: checkout raised: {e}")

    # Reset flags between tests
    if isinstance(flags, dict):
        flags["new_pricing"] = False

    # ── Invariant 2: Generalization — v1 pricing (no discount) ──
    try:
        items2 = [{"sku": "B", "base": 100, "qty": 10}]
        invoice2 = checkout("cust2", items2, use_new_pricing=False)
        total2 = invoice2.get("total")
        if total2 != 1000:
            errors.append(
                f"generalization: v1 pricing total={total2}, expected 1000 "
                f"(no discount: 100*10=1000)"
            )
    except Exception as e:
        errors.append(f"generalization v1: checkout raised: {e}")

    # Reset flags
    if isinstance(flags, dict):
        flags["new_pricing"] = False

    # ── Invariant 3: Generalization — different quantity (below discount threshold) ──
    try:
        items3 = [{"sku": "C", "base": 50, "qty": 5}]
        invoice3 = checkout("cust3", items3, use_new_pricing=True)
        total3 = invoice3.get("total")
        # v2 pricing: qty < 10 → no discount → 50*5=250
        if total3 != 250:
            errors.append(
                f"generalization: small qty total={total3}, expected 250 "
                f"(v2 pricing but qty<10, no discount)"
            )
    except Exception as e:
        errors.append(f"generalization small qty: checkout raised: {e}")

    # ── Invariant 4: Causal-location — flag cleanup ──
    if isinstance(flags, dict):
        if flags.get("new_pricing", False):
            errors.append("causal-location: new_pricing flag left enabled after checkout")

    # ── Invariant 5: Anti-hardcoding — different base price ──
    if isinstance(flags, dict):
        flags["new_pricing"] = False
    try:
        items5 = [{"sku": "D", "base": 200, "qty": 10}]
        invoice5 = checkout("cust5", items5, use_new_pricing=True)
        total5 = invoice5.get("total")
        # v2: 200*10*0.9 = 1800
        if total5 != 1800:
            errors.append(
                f"anti-hardcoding: base=200, total={total5}, expected 1800"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding: checkout raised: {e}")

    if errors:
        return False, errors
    return True, ["v2 pricing applied, v1 pricing works, flag cleaned up, anti-hardcoding passed"]
