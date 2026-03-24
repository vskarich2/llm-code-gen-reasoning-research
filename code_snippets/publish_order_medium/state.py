_state = {}
_captured = []


def set_state(key, value):
    _state[key] = value


def get_state(key):
    return _state.get(key)


def publish_event(event):
    _captured.append({"event": event, "state": get_state(event["key"])})


def get_captures():
    return list(_captured)


def clear():
    _state.clear()
    _captured.clear()
