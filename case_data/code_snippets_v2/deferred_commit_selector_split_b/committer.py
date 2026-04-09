def extract_selected_ref(selection):
    return f"cand::{selection['selected_id']}"


def commit(candidates, selection):
    return candidates[selection['selected_index']]
