from plugins import load_plugins
from dispatcher import dispatch, dispatch_all, list_actions
from registry import get_all


def init():
    load_plugins()
    return list_actions()


def handle(action, data):
    return dispatch(action, data)


def run_all(data):
    return dispatch_all(data)


def snapshot_handlers():
    return dict(get_all())
