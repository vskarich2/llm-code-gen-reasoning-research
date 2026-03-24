from pipeline import process_batch
from selectors import get_committed_total, get_view_digest, get_committed_digest
from reducers import stage
from state import make_state


def ingest(entries):
    st, items = process_batch(entries)
    total = get_committed_total(st)
    return {"items": items, "total": total}


def preview(entries):
    from reducers import normalize, collapse
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    return {"items": list(st["view"]), "frozen": st["meta"]["frozen"]}


def ingest_and_verify(entries):
    """Full pipeline: ingest then verify view is consistent with committed data."""
    st, items = process_batch(entries)
    committed_total = get_committed_total(st)
    view_digest = get_view_digest(st)
    committed_digest = get_committed_digest(st)
    return {
        "items": items,
        "committed_total": committed_total,
        "consistent": view_digest == committed_digest,
    }
