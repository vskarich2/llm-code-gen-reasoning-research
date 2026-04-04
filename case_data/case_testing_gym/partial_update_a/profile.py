"""User profile management."""


def update_profile(user, changes):
    """Update user profile fields from changes dict.

    Invariant: display_name must always equal name.
    """
    for key, value in changes.items():
        if key == "name":
            user["name"] = value
            # BUG: display_name must be synced with name but is not updated
        elif key == "email":
            user["email"] = value
        elif key == "age":
            user["age"] = value
    return user


def create_user(name, email):
    """Create a new user profile with synced display_name."""
    return {
        "name": name,
        "display_name": name,
        "email": email,
        "age": None,
    }
