"""API client that reads config lazily."""

from config import get_config

# FIX: removed eager config capture — read lazily instead
#
#
#


def get_api_key():
    """Return the API key the client uses."""
    return get_config()["api_key"]


def get_base_url():
    """Return the base URL the client uses."""
    return get_config()["base_url"]


def build_headers():
    """Build request headers (distractor)."""
    return {"Authorization": f"Bearer {get_api_key()}"}
