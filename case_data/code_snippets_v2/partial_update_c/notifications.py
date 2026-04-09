def build_greeting(user):
    return "Hello, " + user.get("name", "User") + "!"


def should_reverify(old_email, new_email):
    if old_email is None:
        return True
    return old_email.strip().lower() != new_email.strip().lower()
