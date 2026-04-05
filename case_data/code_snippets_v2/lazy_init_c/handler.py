
from client import get_api_key, get_base_url


def make_request(endpoint):
    return {
        "url": get_base_url() + "/" + endpoint,
        "api_key": get_api_key(),
    }


def health_check():
    return {"status": "ok", "base_url": get_base_url()}


def format_endpoint(base, path):
    return base.rstrip("/") + "/" + path.lstrip("/")
