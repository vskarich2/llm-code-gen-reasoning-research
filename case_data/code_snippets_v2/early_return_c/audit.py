

_log = []


def log_charge(txn_id, amount, source="direct"):

    _log.append({
        "txn_id": txn_id,
        "amount": amount,
        "source": source,
    })


def verify_completeness(expected_count):

    return len(_log) == expected_count


def get_log():

    return list(_log)


def reset_audit():

    _log.clear()
