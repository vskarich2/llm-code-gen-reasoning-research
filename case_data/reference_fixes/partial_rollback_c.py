"""Order service: reserve -> reasoning_evaluator_audit -> pay -> notify."""

from inventory import reserve, release
from payment import process, add_audit_entry, remove_audit_entry
from payment import get_audit_log, set_gateway_fail

_notifications = []


def reset():
    global _notifications, _stock, _reserved, _gateway_fail, _audit_log
    _notifications = []
    _stock = {}
    _reserved = {}
    _gateway_fail = False
    _audit_log = []


def place_order(product_id, qty, price):
    """Place order: reserve inventory, log reasoning_evaluator_audit, process payment, notify.

    If payment fails, must release inventory AND remove reasoning_evaluator_audit entry.
    """
    order_id = f"ORD-{product_id}-{qty}"
    reserve(product_id, qty)
    add_audit_entry({"order_id": order_id, "product": product_id, "qty": qty})
    try:
        result = process(qty * price, order_id)
    except ValueError:
        release(product_id, qty)  # FIX: rollback reservation
        remove_audit_entry(order_id)  # FIX: rollback reasoning_evaluator_audit entry
        raise
    _notifications.append({"order_id": order_id, "status": "confirmed"})
    return {"status": "confirmed", "payment": result}


def retry_payment(product_id, qty, price):
    """Trap: adding retry on payment makes partial state worse."""
    order_id = f"ORD-{product_id}-{qty}"
    for attempt in range(3):
        try:
            return process(qty * price, order_id)
        except ValueError:
            continue
    return None


def get_notifications():
    return list(_notifications)
