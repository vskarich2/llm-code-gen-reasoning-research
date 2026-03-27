def process_refund(merchant, customer, amount, partial=False):
    if partial:
        fee = round(amount * 0.1, 2)
        merchant["balance"] -= amount - fee
        customer["balance"] += amount  # BUG: should be (amount - fee)
        return {"fee": fee, "refunded": amount - fee}
    else:
        merchant["balance"] -= amount
        customer["balance"] += amount
        return {"fee": 0, "refunded": amount}
