from models import Inventory, Wallet
from notifications import send_confirmation, send_failure_notice

inventory = Inventory()
wallet = Wallet(balance=1000)


def place_order(order_id, sku, qty, price):
    total = qty * price

    inventory.reserve(sku, qty)

    wallet.charge(total)

    send_confirmation(order_id)

    return {"order_id": order_id, "charged": total, "reserved": qty}


def cancel_order(order_id, sku, qty, price):
    inventory.release(sku, qty)
    wallet.refund(qty * price)
