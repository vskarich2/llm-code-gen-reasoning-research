def transfer(src, dst, amount):
    if src["balance"] < amount:
        raise ValueError("insufficient funds")
    src["balance"] -= amount
    dst["balance"] += amount


def get_total(*accounts):
    return sum(a["balance"] for a in accounts)
