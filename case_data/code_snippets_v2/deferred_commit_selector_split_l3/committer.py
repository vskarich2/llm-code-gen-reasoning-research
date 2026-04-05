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

    # BUG: resolves using positional + fallback heuristic
    if len(normalized) > 1 and normalized[0]["normalized_score"] > normalized[1]["normalized_score"]:
        chosen = normalized[0]
    else:
        chosen = next(n for n in normalized if n["payload"].startswith(selected["payload"][0].upper()))

    STORE["result"] = chosen
    return chosen


def reset():
    STORE.clear()
    LOG.clear()
