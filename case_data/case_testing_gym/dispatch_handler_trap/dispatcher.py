from handlers import handle_standard, handle_priority, handle_batch

_dispatch_table = {
    "standard": handle_standard,
    "priority": handle_standard,   # BUG: should be handle_priority
    "batch": handle_batch,
}


def dispatch(event):
    event_type = event.get("type", "standard")
    handler = _dispatch_table.get(event_type)
    if handler is None:
        raise ValueError(f"Unknown event type: {event_type}")
    return handler(event)


def process_queue(events):
    results = []
    for event in events:
        results.append(dispatch(event))
    return results


def get_dispatch_table():
    return dict(_dispatch_table)


def reset():
    pass
