from bootstrap import init_app
from client import make_request, make_debug_request


def start(env="production"):
    init_app(env)
    return make_request("/health")


def run_diagnostics():
    return make_debug_request("/diagnostics")
