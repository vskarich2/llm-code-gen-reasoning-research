from state import make_state
from reducers import normalize, collapse, stage, commit, freeze_view, materialize


def process_batch(entries):
    st = make_state(entries)
    cleaned = normalize(st["raw"])
    merged = collapse(cleaned)
    stage(st, merged)
    commit(st)       # FIX: restored — sets frozen gate + sorts into stable
    freeze_view(st)  # FIX: restored — rebuilds view from committed stable
    return st, materialize(st)
