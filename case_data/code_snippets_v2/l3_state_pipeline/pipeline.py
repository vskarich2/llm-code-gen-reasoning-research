from state import make_state, copy_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize, project


def process_batch(entries):
    st = make_state(entries)
    raw = st["raw"]


    cleaned = normalize(raw)

    merged = collapse(cleaned)

    stage(st, merged)

    out = materialize(st)
    return st, out


def process_incremental(prev_state, new_entries):
    st = copy_state(prev_state)
    combined = st["stable"] + new_entries

    cleaned = normalize(combined)
    merged = collapse(cleaned)

    stage(st, merged)

    out = materialize(st)
    return st, out


def recompute_view(st):
    st["view"] = project(st["pending"])
    return st
