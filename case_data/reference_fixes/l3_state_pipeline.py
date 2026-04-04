from state import make_state, copy_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize, project


def process_batch(entries):
    st = make_state(entries)
    raw = st["raw"]

    # dedupe
    cleaned = normalize(raw)

    # merge values for same id
    merged = collapse(cleaned)

    # stage puts merged into pending + builds view from merged
    stage(st, merged)

    # commit copies pending -> stable and sets frozen=True
    commit(st)

    # freeze_view rebuilds view from stable (overwriting the staged view)
    # NOTE: after commit, stable == pending, so this is a no-op in the
    # normal path. but commit sets frozen=True which downstream selectors
    # check before reading stable.
    freeze_view(st)

    out = materialize(st)
    return st, out


def process_incremental(prev_state, new_entries):
    st = copy_state(prev_state)
    combined = st["stable"] + new_entries

    cleaned = normalize(combined)
    merged = collapse(cleaned)

    stage(st, merged)
    commit(st)
    freeze_view(st)

    out = materialize(st)
    return st, out


def recompute_view(st):
    st["view"] = project(st["pending"])
    return st
