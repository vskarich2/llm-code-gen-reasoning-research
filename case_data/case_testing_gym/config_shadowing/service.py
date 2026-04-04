from env_config import get_config
from defaults import get_defaults


def handle_request():
    return {"timeout": get_config()["timeout"], "source": "request"}


def run_background_job():
    return {"timeout": get_defaults()["timeout"], "source": "background"}


def run_system_check():
    return {"request": handle_request(), "background": run_background_job()}
