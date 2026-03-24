"""Request handler that uses client."""

from client import get_api_key, get_base_url


def make_request(endpoint):
    """Build a request dict using client config.

    Invariant: must reflect current config, not stale import-time snapshot.
    """
    return {
        "url": get_base_url() + "/" + endpoint,
        "api_key": get_api_key(),
    }


def health_check():
    """Health check endpoint (distractor)."""
    return {"status": "ok", "base_url": get_base_url()}


def format_endpoint(base, path):
    """URL formatter (distractor)."""
    return base.rstrip("/") + "/" + path.lstrip("/")
