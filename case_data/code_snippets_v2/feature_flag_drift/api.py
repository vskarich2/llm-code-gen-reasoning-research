from billing import create_invoice, get_invoices
from flags import enable, disable


def checkout(customer, items, use_new_pricing=False):
    invoice = create_invoice(customer, items)
    return invoice


def admin_report():
    return get_invoices()
