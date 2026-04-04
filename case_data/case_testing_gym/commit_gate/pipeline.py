from state import make_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize


def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    # commit(st)       — removed as "redundant"
    # freeze_view(st)  — removed as "redundant"
    return st, materialize(st)
