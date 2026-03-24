from registry import register


def _handle_greet(data):
    return f"Hello, {data.get('name', 'world')}"


def _handle_farewell(data):
    return f"Goodbye, {data.get('name', 'world')}"


def _handle_echo(data):
    return data


def load_plugins():
    register("greet", _handle_greet)
    register("farewell", _handle_farewell)
    register("echo", _handle_echo)
