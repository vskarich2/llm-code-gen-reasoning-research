"""Reference fix: resolve committed artifact via lineage key (meta.src)."""

STORE = {}
LOG = {}


def run_pipeline():
    from planner import generate_candidates
    from selector import choose_best
    from snapshot_store import snapshot
    from normalizer import normalize

    candidates = generate_candidates()
    selected = choose_best(candidates)

    LOG["selected"] = selected

    snap = snapshot(candidates)
    normalized = normalize(snap)

    # FIX: resolve by lineage, not position or heuristic
    selected_src = selected["source_id"]
    chosen = None
    for n in normalized:
        if n["meta"]["src"] == selected_src:
            chosen = n
            break
    if chosen is None:
        raise KeyError(f"No normalized artifact with meta.src={selected_src}")

    STORE["result"] = chosen
    return chosen


def reset():
    STORE.clear()
    LOG.clear()
