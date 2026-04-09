


def validate_name(name):
    return isinstance(name, str) and len(name.strip()) > 0


def validate_email(email):
    return isinstance(email, str) and "@" in email


def sanitize_string(value):
    if isinstance(value, str):
        return value.strip()
    return value
