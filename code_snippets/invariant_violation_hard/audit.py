_alerts = []


def emit_transfer_event(from_id, to_id, amount):
    _alerts.append(
        {
            "event": "transfer",
            "from": from_id,
            "to": to_id,
            "amount": amount,
        }
    )


def emit_failure_alert(from_id, to_id, amount, error):
    _alerts.append(
        {
            "event": "transfer_failure",
            "from": from_id,
            "to": to_id,
            "amount": amount,
            "error": str(error),
        }
    )


def get_alerts():
    return list(_alerts)
