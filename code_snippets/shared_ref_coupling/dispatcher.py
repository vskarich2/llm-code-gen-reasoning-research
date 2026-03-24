from registry import get_handler, get_all


def dispatch(action, data):
    fn = get_handler(action)
    if fn is None:
        raise KeyError(f"no handler for {action}")
    return fn(data)


def list_actions():
    return list(get_all().keys())


def dispatch_all(data):
    results = {}
    handlers = get_all()
    for name, fn in handlers.items():
        results[name] = fn(data)
    return results
