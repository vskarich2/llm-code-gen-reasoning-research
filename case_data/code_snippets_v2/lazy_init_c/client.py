"""API client that reads config at import time."""

from config import get_config

# BUG: captures config dict reference at import time.
# After reset_config(), _config in config.py becomes a NEW dict,
# but _client_cfg still points to the OLD one.
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
