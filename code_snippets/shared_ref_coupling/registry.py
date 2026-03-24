_handlers = {}


def register(name, fn):
    _handlers[name] = fn


def get_handler(name):
    return _handlers.get(name)


def get_all():
    return _handlers


def clear():
    _handlers.clear()
