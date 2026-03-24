from service import update_value, get_log, clear


def process(key, value):
    store = {}
    clear()
    update_value(store, key, value)
    log = get_log()
    return {"stored": store[key], "logged": log[-1]["value"]}
