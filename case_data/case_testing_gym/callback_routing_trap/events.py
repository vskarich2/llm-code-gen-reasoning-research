_handlers = {}
_log = []


def register(event_type, handler):
    _handlers[event_type] = handler


def emit(event_type, payload):
    handler = _handlers.get(event_type)
    if handler is None:
        _log.append(("unhandled", event_type, payload))
        return None
    result = handler(payload)
    _log.append(("handled", event_type, payload))
    return result


def get_log():
    return list(_log)


def reset():
    _handlers.clear()
    _log.clear()
