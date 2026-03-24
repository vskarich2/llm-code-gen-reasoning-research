from pricing import compute_price, get_pricing_version
from flags import is_enabled

_invoices = []


def create_invoice(customer, items):
    total = 0
    lines = []
    for item in items:
        price = compute_price(item["base"], item["qty"])
        lines.append({"sku": item["sku"], "amount": price})
        total += price

    invoice = {
        "customer": customer,
        "lines": lines,
        "total": total,
        "pricing_version": get_pricing_version(),
    }

    if is_enabled("audit_mode"):
        invoice["audit"] = True
        _invoices.append(invoice)

    return invoice


def get_invoices():
    return list(_invoices)
