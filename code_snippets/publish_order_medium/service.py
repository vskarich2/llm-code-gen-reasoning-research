from state import set_state, publish_event


def update_and_notify(key, value):
    publish_event({"key": key, "value": value})    # BUG: before set_state
    set_state(key, value)
