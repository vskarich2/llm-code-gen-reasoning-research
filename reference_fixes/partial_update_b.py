"""User profile with derived full_name field."""

from validation import validate_name, sanitize_string


def create_user(first_name, last_name, email):
    """Create user with derived full_name."""
    return {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": first_name + " " + last_name,
        "email": email,
    }


def update_profile(user, changes):
    """Update profile fields. full_name must stay in sync.

    Invariant: full_name == first_name + ' ' + last_name
    """
    for key, value in changes.items():
        value = sanitize_string(value)
        if key == "first_name" and validate_name(value):
            user["first_name"] = value
            user["full_name"] = value + " " + user["last_name"]  # FIX: sync full_name
        elif key == "last_name" and validate_name(value):
            user["last_name"] = value
            user["full_name"] = user["first_name"] + " " + value
        elif key == "email":
            user["email"] = value
    return user
