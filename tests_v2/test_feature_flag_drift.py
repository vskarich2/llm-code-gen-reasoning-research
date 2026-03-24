"""Test for feature_flag_drift: use_new_pricing flag must propagate to pricing.

Invariant: checkout("cust1", [{sku:"A", base:100, qty:10}], use_new_pricing=True)
must apply v2 pricing (10% discount for qty>=10), giving total=900.
If the flag does not propagate, v1 pricing is used and total=1000.
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

    try:
        items = [{"sku": "A", "base": 100, "qty": 10}]
        invoice = checkout("cust1", items, use_new_pricing=True)
    except Exception as e:
        return False, [f"checkout raised: {e}"]

    total = invoice.get("total")
    if total is None:
        return False, ["invoice missing 'total' field"]

    # v2 pricing: 100 * 10 * (1 - 0.1) = 900
    # v1 pricing: 100 * 10 = 1000
    if total != 900:
        return False, [
            f"total={total}, expected 900 (v2 pricing with 10% discount). "
            f"Flag did not propagate to compute_price."
        ]

    # Verify the flag is cleaned up (not left enabled)
    if flags is not None and flags.get("new_pricing", False):
        return False, ["new_pricing flag left enabled after checkout"]

    return True, ["use_new_pricing flag properly propagated, total=900"]
