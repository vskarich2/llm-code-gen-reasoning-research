import random

_sent = []


def send_confirmation(order_id):
    if random.random() < 0.2:
        raise ConnectionError("email service down")
    _sent.append(order_id)


def send_failure_notice(order_id, reason):
    _sent.append({"order": order_id, "failed": reason})


def get_sent():
    return list(_sent)
