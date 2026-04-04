from api import get_record


class NotFoundError(Exception):
    pass


def get_user_display(user_id):
    record = get_record(user_id)
    # Crashes with AttributeError when record is None (not found)
    return f"{record['name']} ({record['id']})"


def get_user_status(user_id):
    record = get_record(user_id)
    if record is None:
        return "unknown"
    return "active" if record.get("active") else "inactive"


def format_user_card(user_id):
    record = get_record(user_id)
    name = record["name"]
    status = "active" if record.get("active") else "inactive"
    return f"[{status}] {name}"
