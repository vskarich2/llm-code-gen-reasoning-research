def validate_email(email):
    return isinstance(email, str) and "@" in email and "." in email


def validate_name(name):
    return isinstance(name, str) and len(name.strip()) > 0
