class Account:
    def __init__(self, account_id, balance):
        self.account_id = account_id
        self.balance = balance

    def __repr__(self):
        return f"Account({self.account_id}, balance={self.balance})"
