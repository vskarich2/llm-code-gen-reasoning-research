def debit(account, amount):
    account["balance"] -= amount


def credit(account, amount):
    account["balance"] += amount
