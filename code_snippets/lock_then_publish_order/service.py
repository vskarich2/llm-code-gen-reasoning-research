from state import set_state, publish_event, acquire_lock, release_lock


def _broadcast(key, value):
    publish_event({"key": key, "value": value, "type": "update"})


def _apply_update(key, value):
    set_state(key, value)


def update_and_notify(key, value):
    acquire_lock()
    _broadcast(key, value)
    _apply_update(key, value)
    release_lock()
