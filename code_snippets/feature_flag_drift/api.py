from billing import create_invoice, get_invoices
from flags import enable, disable


def checkout(customer, items, use_new_pricing=False):
    if use_new_pricing:
        enable("new_pricing")
    invoice = create_invoice(customer, items)
    if use_new_pricing:
        disable("new_pricing")
    return invoice


def admin_report():
    return get_invoices()
