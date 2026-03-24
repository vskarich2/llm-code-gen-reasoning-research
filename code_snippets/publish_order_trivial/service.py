_state = {}
_captured = []


def get_state(key):
    return _state.get(key)


def get_captures():
    return list(_captured)


def clear():
    _state.clear()
    _captured.clear()


def update_and_notify(key, value):
    _captured.append({"key": key, "state_at_publish": _state.get(key)})
    _state[key] = value
