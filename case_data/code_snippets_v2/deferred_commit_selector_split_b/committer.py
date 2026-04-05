def extract_selected_ref(selection):
    return f"cand::{selection['selected_id']}"


def commit(candidates, selection):
    # BUG: stale positional resolution from pre-normalized ordering.
    # This often looks correct when the selected candidate stays top-ranked,
    # which makes local fixes like re-ranking seem appealing.
    return candidates[selection['selected_index']]
