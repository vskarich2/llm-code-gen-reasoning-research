

from config import get_config

_client_config = get_config()


def get_db_url():

    return _client_config["db_url"]


def get_timeout():

    return _client_config["timeout"]


def connect():
    return {"status": "connected", "url": get_db_url()}
