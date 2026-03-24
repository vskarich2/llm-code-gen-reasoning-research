class Inventory:
    def __init__(self):
        self.stock = {}

    def reserve(self, sku, qty):
        avail = self.stock.get(sku, 0)
        if avail < qty:
            raise ValueError(f"insufficient stock for {sku}")
        self.stock[sku] = avail - qty

    def release(self, sku, qty):
        self.stock[sku] = self.stock.get(sku, 0) + qty


class Wallet:
    def __init__(self, balance=0):
        self.balance = balance

    def charge(self, amount):
        if self.balance < amount:
            raise ValueError("insufficient funds")
        self.balance -= amount

    def refund(self, amount):
        self.balance += amount
