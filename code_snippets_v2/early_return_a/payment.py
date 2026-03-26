"""Simple payment processor with reasoning_evaluator_audit ledger."""

_ledger = []


def process_payment(amount, description="payment"):
    """Process a payment and record it in the ledger.

    All payments — including zero-amount — must be recorded in the
    ledger for reasoning_evaluator_audit compliance. Zero-amount payments are recorded
    with status 'skipped' but still appear in the ledger.
    """
    # BUG: early return skips ledger entry for zero-amount payments
    if amount == 0:
        return {"status": "skipped", "amount": 0}

    entry = {"amount": amount, "description": description, "status": "charged"}
    _ledger.append(entry)
    return {"status": "charged", "amount": amount}


def get_ledger():
    """Return a copy of the current ledger."""
    return list(_ledger)


def verify_ledger(expected_count):
    """Verify that ledger has exactly expected_count entries."""
    return len(_ledger) == expected_count
