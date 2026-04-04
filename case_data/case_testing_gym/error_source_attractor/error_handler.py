from validator import validate_input

_ERROR_MESSAGES = {
    "REQUIRED": "This field is required",
    "TOO_SHORT": "Value is too short",
    "INVALID_FORMAT": "Invalid format",
    "OUT_OF_RANGE": "Value is out of range",
    "INVALID_TYPE": "Invalid type",
}


def format_errors(data):
    errors = validate_input(data)
    formatted = []
    for err in errors:
        code = err["code"]
        msg = _ERROR_MESSAGES.get(code, f"Unknown error: {code}")
        formatted.append({
            "field": err["field"],
            "code": code,
            "message": msg,
        })
    return formatted


def get_error_summary(data):
    formatted = format_errors(data)
    if not formatted:
        return "No errors"
    parts = [f"{e['field']}: {e['message']}" for e in formatted]
    return "; ".join(parts)


def has_format_errors(data):
    errors = validate_input(data)
    return any(e["code"] == "INVALID_FORMAT" for e in errors)
