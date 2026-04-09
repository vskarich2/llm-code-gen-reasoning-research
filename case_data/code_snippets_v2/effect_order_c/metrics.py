

_counter = 0
_events = []


def reset():
    global _counter, _events
    _counter = 0
    _events = []


def increment(value):
    global _counter
    _counter += value

def emit_event(item_id, value):
    _events.append({"item_id": item_id, "value": value, "counter": _counter})


def get_counter():
    return _counter


def get_events():
    return list(_events)
