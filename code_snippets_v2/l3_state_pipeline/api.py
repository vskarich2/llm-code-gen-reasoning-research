from pipeline import process_batch, process_incremental
from selectors import get_committed_total, get_display_items, summary_for_display, compute_drift


def ingest(entries):
    st, out = process_batch(entries)
    total = get_committed_total(st)
    display = summary_for_display(st)
    return {"total": total, "display": display, "materialized": out}


def update(prev_state, new_entries):
    st, out = process_incremental(prev_state, new_entries)
    total = get_committed_total(st)
    drift = compute_drift(st)
    return {"total": total, "drift": drift, "materialized": out}


def preview(entries):
    from state import make_state
    from reducers import normalize, collapse, stage, project
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    # no commit — preview only
    return get_display_items(st)
