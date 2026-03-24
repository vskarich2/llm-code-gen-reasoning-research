from workflow import transition


def submit_and_approve(item):
    transition(item, "submitted")
    transition(item, "approved")
    return item["status"]
