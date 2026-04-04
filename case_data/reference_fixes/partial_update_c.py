"""User profile with email verification and cached greeting."""

from validation import validate_email, validate_name
from notifications import build_greeting, should_reverify


def create_user(name, email):
    """Create a user with verified status and cached greeting."""
    return {
        "name": name,
        "email": email,
        "verified": False,
        "cached_greeting": build_greeting({"name": name}),
    }


def verify_user(user):
    """Mark user as verified."""
    user["verified"] = True
    return user


def update_profile(user, changes):
    """Update profile fields.

    Invariant: changing email must set verified=False and clear cached_greeting.
    Invariant: changing name must update cached_greeting.
    """
    for key, value in changes.items():
        if key == "email" and validate_email(value):
            old_email = user.get("email")
            user["email"] = value
            if should_reverify(old_email, value):  # FIX: reset verified and greeting
                user["verified"] = False
                user["cached_greeting"] = build_greeting(user)
        elif key == "name" and validate_name(value):
            user["name"] = value
            user["cached_greeting"] = build_greeting(user)
    return user
