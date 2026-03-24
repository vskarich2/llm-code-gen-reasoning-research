"""Database client that uses config."""

from config import get_config

# FIX: removed eager config capture — read lazily instead
#
#

def get_db_url():
    """Return the database URL the client is using."""
    return get_config()["db_url"]


def get_timeout():
    """Return the timeout the client is using."""
    return get_config()["timeout"]


def connect():
    """Simulate connection (distractor)."""
    return {"status": "connected", "url": get_db_url()}
