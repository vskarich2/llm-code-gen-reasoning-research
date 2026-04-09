
_ledger = []

def process_payment(amount, description="payment"):
    if amount == 0:
        return {"status": "skipped", "amount": 0}

    entry = {"amount": amount, "description": description, "status": "charged"}
    _ledger.append(entry)
    return {"status": "charged", "amount": amount}


def get_ledger():
    return list(_ledger)


def verify_ledger(expected_count):
    return len(_ledger) == expected_count
