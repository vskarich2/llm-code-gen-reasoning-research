_count = 0
_history = []


def increment(amount=1):
    global _count
    _count += amount
    _history.append(("inc", amount, _count))


def get_count():
    return _count


def get_history():
    return list(_history)


def reset():
    global _count
    _count = 0
    _history.clear()
