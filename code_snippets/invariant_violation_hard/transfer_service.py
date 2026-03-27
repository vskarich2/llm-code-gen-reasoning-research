import random
from models import Account
from ledger import record_debit, record_credit, record_transfer_attempt
from audit import emit_transfer_event, emit_failure_alert


def validate_transfer(sender, amount):
    if amount <= 0:
        raise ValueError("amount must be positive")
    if sender.balance < amount:
        raise ValueError("insufficient funds")


def execute_transfer(sender, receiver, amount):
    validate_transfer(sender, amount)

    record_transfer_attempt(sender.account_id, receiver.account_id, amount)

    sender.balance -= amount
    record_debit(sender.account_id, amount)

    if random.random() < 0.3:
        emit_failure_alert(
            sender.account_id,
            receiver.account_id,
            amount,
            "connection reset during credit phase",
        )
        raise RuntimeError("transient failure during credit")

    receiver.balance += amount
    record_credit(receiver.account_id, amount)

    emit_transfer_event(sender.account_id, receiver.account_id, amount)
