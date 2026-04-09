from inventory import reserve, release

_notifications = []
_gateway_fail = False

def reset():
    global _notifications, _gateway_fail, _stock, _reserved
    _notifications = []
    _gateway_fail = False
    _stock = {}
    _reserved = {}

def set_gateway_fail(fail):
    global _gateway_fail
    _gateway_fail = fail

def _process_payment(amount):
    if _gateway_fail:
        raise ValueError("payment declined")
    return {"paid": amount}


def place_order(product_id, qty, price):
    reserve(product_id, qty)
    try:
        result = _process_payment(qty * price)
    except ValueError:
        raise
    _notifications.append({"product": product_id, "qty": qty})
    return {"status": "confirmed", "payment": result}


def get_notifications():
    return list(_notifications)
