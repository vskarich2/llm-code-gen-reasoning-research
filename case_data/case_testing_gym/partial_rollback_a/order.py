"""Order fulfillment with inventory and wallet."""


class Inventory:
    def __init__(self, stock):
        self.stock = stock
        self.reserved = 0

    def reserve(self, qty):
        if qty > self.stock - self.reserved:
            raise ValueError("insufficient stock")
        self.reserved += qty

    def release(self, qty):
        self.reserved -= qty

    def available(self):
        return self.stock - self.reserved


class Wallet:
    def __init__(self, balance):
        self.balance = balance

    def charge(self, amount):
        if amount > self.balance:
            raise ValueError("insufficient funds")
        self.balance -= amount


def place_order(inventory, wallet, qty, price):
    """Reserve inventory, then charge wallet. Release on failure."""
    inventory.reserve(qty)
    try:
        wallet.charge(qty * price)
    except ValueError:
        raise  # BUG: re-raises without releasing inventory reservation
    return {"status": "confirmed", "qty": qty, "total": qty * price}
