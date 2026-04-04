_counter = {"value": 0, "locked": False}


def get_counter():
    return _counter["value"]


def increment(n=1):
    _counter["value"] += n


def try_lock():
    if _counter["locked"]:
        return False
    _counter["locked"] = True
    return True


def unlock():
    _counter["locked"] = False


def reset():
    _counter["value"] = 0
    _counter["locked"] = False
