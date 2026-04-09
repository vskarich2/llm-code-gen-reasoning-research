

_gateway_fail = False
_audit_log = []


def reset():
    global _gateway_fail, _audit_log
    _gateway_fail = False
    _audit_log = []


def set_gateway_fail(fail):
    global _gateway_fail
    _gateway_fail = fail


def process(amount, order_id):
    if _gateway_fail:
        raise ValueError("payment declined")
    return {"paid": amount, "order_id": order_id}


def add_audit_entry(entry):
    _audit_log.append(entry)


def remove_audit_entry(order_id):
    global _audit_log
    _audit_log = [e for e in _audit_log if e.get("order_id") != order_id]


def get_audit_log():
    return list(_audit_log)
