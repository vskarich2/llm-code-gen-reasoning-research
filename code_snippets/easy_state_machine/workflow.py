_VALID_TRANSITIONS = {
    "draft": ["submitted"],
    "submitted": ["approved", "rejected"],
    "approved": [],
    "rejected": [],
}


def transition(item, new_status):
    current = item["status"]
    allowed = _VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise ValueError(f"cannot go from {current} to {new_status}")
    item["status"] = new_status
