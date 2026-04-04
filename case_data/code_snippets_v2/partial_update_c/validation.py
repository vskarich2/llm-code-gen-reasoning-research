"""Validation helpers for profile updates."""


def validate_email(email):
    """Return True if email looks valid."""
    return isinstance(email, str) and "@" in email and "." in email


def validate_name(name):
    """Return True if name is a non-empty string."""
    return isinstance(name, str) and len(name.strip()) > 0
