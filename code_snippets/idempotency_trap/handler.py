from processor import process_event, replay_events
from store import get_apply_log


def handle_with_retry(event, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = process_event(event)
            return {"ok": True, "value": result, "attempt": attempt}
        except Exception:
            continue
    return {"ok": False, "value": None}


def handle_batch(events):
    return replay_events(events)


def get_audit_trail():
    return get_apply_log()
