"""Validation helpers for profile updates."""


def validate_name(name):
    """Return True if name is a non-empty string."""
    return isinstance(name, str) and len(name.strip()) > 0


def validate_email(email):
    """Return True if email contains '@'."""
    return isinstance(email, str) and "@" in email


def sanitize_string(value):
    """Strip whitespace from string values."""
    if isinstance(value, str):
        return value.strip()
    return value
