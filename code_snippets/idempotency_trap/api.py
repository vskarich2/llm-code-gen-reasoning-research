from handler import handle_with_retry, handle_batch, get_audit_trail
from store import clear


def ingest(events):
    clear()
    results = handle_batch(events)
    trail = get_audit_trail()
    return {"results": results, "audit_count": len(trail)}


def ingest_with_retry(events):
    clear()
    results = []
    for e in events:
        results.append(handle_with_retry(e))
    trail = get_audit_trail()
    return {"results": results, "audit_count": len(trail)}
