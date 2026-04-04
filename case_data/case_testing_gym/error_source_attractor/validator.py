def validate_input(data):
    errors = []
    if "name" not in data:
        errors.append({"field": "name", "code": "REQUIRED"})
    elif len(data["name"]) < 2:
        errors.append({"field": "name", "code": "TOO_SHORT"})

    if "email" not in data:
        errors.append({"field": "email", "code": "REQUIRED"})
    elif "@" not in data.get("email", ""):
        # BUG: wrong error code — should be "INVALID_FORMAT" not "REQUIRED"
        errors.append({"field": "email", "code": "REQUIRED"})

    if "age" in data:
        try:
            age = int(data["age"])
            if age < 0 or age > 150:
                errors.append({"field": "age", "code": "OUT_OF_RANGE"})
        except (ValueError, TypeError):
            errors.append({"field": "age", "code": "INVALID_TYPE"})

    return errors


def is_valid(data):
    return len(validate_input(data)) == 0
