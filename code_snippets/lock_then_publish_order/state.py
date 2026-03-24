_state = {}
_captured = []
_locked = False


def set_state(key, value):
    _state[key] = value


def get_state(key):
    return _state.get(key)


def publish_event(event):
    snapshot = get_state(event["key"])
    _captured.append({"event": event, "state_at_publish": snapshot})


def get_captures():
    return list(_captured)


def acquire_lock():
    global _locked
    _locked = True


def release_lock():
    global _locked
    _locked = False


def clear():
    _state.clear()
    _captured.clear()
    global _locked
    _locked = False
