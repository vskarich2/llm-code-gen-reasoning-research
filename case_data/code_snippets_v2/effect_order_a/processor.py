

_counter = 0
_snapshots = []


def reset():
    global _counter, _snapshots
    _counter = 0
    _snapshots = []


def snapshot():

    _snapshots.append(_counter)


def get_snapshots():
    return list(_snapshots)


def process_batch(items):
    global _counter
    for item in items:
        _counter += item
    snapshot()
    return _counter


def verify_consistency():
    return len(_snapshots)
