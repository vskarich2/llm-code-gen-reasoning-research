_entries = []


def record_debit(account_id, amount):
    _entries.append({"type": "debit", "account": account_id, "amount": amount})


def record_credit(account_id, amount):
    _entries.append({"type": "credit", "account": account_id, "amount": amount})


def record_transfer_attempt(from_id, to_id, amount, status="pending"):
    _entries.append({
        "type": "transfer_attempt",
        "from": from_id, "to": to_id,
        "amount": amount, "status": status,
    })


def get_entries():
    return list(_entries)
