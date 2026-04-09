

from config import get_config

_client_cfg = get_config()


def get_api_key():
    return _client_cfg["api_key"]


def get_base_url():
    return _client_cfg["base_url"]


def build_headers():
    return {"Authorization": f"Bearer {get_api_key()}"}
