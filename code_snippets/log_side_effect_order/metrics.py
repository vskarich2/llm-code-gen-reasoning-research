_counters = {}
_snapshots = []


def inc(name, n=1):
    _counters[name] = _counters.get(name, 0) + n


def get_count(name):
    return _counters.get(name, 0)


def snapshot():
    _snapshots.append(dict(_counters))


def get_snapshots():
    return list(_snapshots)


def reset():
    _counters.clear()
    _snapshots.clear()
