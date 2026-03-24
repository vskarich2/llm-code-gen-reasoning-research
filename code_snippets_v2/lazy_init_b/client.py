"""Database client that uses config."""

from config import get_config

# BUG: config captured eagerly at import time — reset_config won't affect this
_client_config = get_config()


def get_db_url():
    """Return the database URL the client is using."""
    return _client_config["db_url"]


def get_timeout():
    """Return the timeout the client is using."""
    return _client_config["timeout"]


def connect():
    """Simulate connection (distractor)."""
    return {"status": "connected", "url": get_db_url()}
