"""API client that reads config at import time."""

from config import get_config

_client_cfg = get_config()


def get_api_key():
    """Return the API key the client uses."""
    return _client_cfg["api_key"]


def get_base_url():
    """Return the base URL the client uses."""
    return _client_cfg["base_url"]


def build_headers():
    """Build request headers (distractor)."""
    return {"Authorization": f"Bearer {get_api_key()}"}
