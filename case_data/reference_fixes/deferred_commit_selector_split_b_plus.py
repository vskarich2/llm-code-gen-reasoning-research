"""Reference fix: resolve by identity across representation boundary."""


def extract_selected_ref(selection):
    return f"cand::{selection['selected_id']}"


def commit(candidates, selection):
    target_ref = extract_selected_ref(selection)
    for c in candidates:
        if c['origin_ref'] == target_ref:
            return c
    raise KeyError(selection['selected_id'])
