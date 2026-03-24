from order_service import place_order, cancel_order


def checkout(order_id, sku, qty, price):
    return place_order(order_id, sku, qty, price)


def refund(order_id, sku, qty, price):
    return cancel_order(order_id, sku, qty, price)
