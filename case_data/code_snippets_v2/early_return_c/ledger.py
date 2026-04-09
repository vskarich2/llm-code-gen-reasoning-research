_entries = []

def record(txn_id, amount, status):
    _entries.append({
        "txn_id": txn_id,
        "amount": amount,
        "status": status,
    })

def get_total():
    return sum(e["amount"] for e in _entries)


def get_count():
    return len(_entries)


def reset_ledger():
    _entries.clear()
