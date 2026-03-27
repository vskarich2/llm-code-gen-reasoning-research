from accounts import debit, credit


def compute_fee(amount, rate=0.1):
    return round(amount * rate, 2)


def compute_net(amount, fee):
    return amount - fee


def process_refund(merchant, customer, amount, partial=False):
    if partial:
        fee = compute_fee(amount)
        net = compute_net(amount, fee)
        debit(merchant, net)
        credit(customer, amount)  # BUG: should be net
        return {"fee": fee, "refunded": net}
    else:
        debit(merchant, amount)
        credit(customer, amount)
        return {"fee": 0, "refunded": amount}
