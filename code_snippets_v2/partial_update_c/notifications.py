"""Notification helpers for profile changes."""


def build_greeting(user):
    """Build a cached greeting string for the user."""
    return "Hello, " + user.get("name", "User") + "!"


def should_reverify(old_email, new_email):
    """Determine if email change requires re-verification."""
    if old_email is None:
        return True
    return old_email.strip().lower() != new_email.strip().lower()
