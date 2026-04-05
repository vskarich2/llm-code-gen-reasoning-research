"""Tests for deferred_commit_selector_split family.

Invariant: committed artifact must correspond to the selected candidate
by identity/lineage, not by position or heuristic.

B+: cross-stage identity via origin_ref after normalization reorders.
L3: cross-stage lineage via meta.src across snapshot+normalization+commit.
"""


def test_b(mod):
    """B+ variant: pipeline with selector, snapshot, normalizer, committer."""
    errors = []

    run = getattr(mod, "run", None)
    extract_selected_ref = getattr(mod, "extract_selected_ref", None)
    if run is None:
        return False, ["run function not found"]

    # Candidates where raw-score winner differs from transformed-score winner
    # a: score=90, penalty=5 → final=85
    # b: score=80, penalty=0 → final=80
    # c: score=85, penalty=40 → final=45
    # Raw winner: a (score=90). After normalization: a(85), b(80), c(45). a stays top.
    # BUT with different penalties:
    candidates = [
        {"id": "a", "score": 90, "penalty": 50},  # final=40
        {"id": "b", "score": 80, "penalty": 0},    # final=80
        {"id": "c", "score": 85, "penalty": 10},   # final=75
    ]
    # Raw winner: a (score=90). After normalization order: b(80), c(75), a(40).
    # Commit must still pick a, not b.

    try:
        selection, result = run(candidates)
        selected_id = selection["selected_id"]
        expected_ref = f"cand::{selected_id}"

        if selected_id != "a":
            errors.append(f"selector: chose '{selected_id}', expected 'a'")

        committed_ref = result.get("origin_ref", "")
        if committed_ref != expected_ref:
            errors.append(
                f"invariant 1: committed origin_ref='{committed_ref}', "
                f"expected '{expected_ref}'. Positional resolution failed "
                f"after normalization reorder."
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # Anti-hardcoding: different candidate set
    candidates2 = [
        {"id": "x", "score": 100, "penalty": 90},  # final=10
        {"id": "y", "score": 50, "penalty": 0},     # final=50
    ]
    try:
        sel2, res2 = run(candidates2)
        if sel2["selected_id"] != "x":
            errors.append(f"anti-hardcoding: selected '{sel2['selected_id']}', expected 'x'")
        if res2.get("origin_ref") != "cand::x":
            errors.append(
                f"anti-hardcoding: committed '{res2.get('origin_ref')}', expected 'cand::x'"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # Structural
    for name in ("run", "choose_best", "snapshot", "normalize", "commit"):
        if not callable(getattr(mod, name, None)):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, ["committed matches selection by identity", "anti-hardcoding passed"]


def test_c(mod):
    """L3 variant: full pipeline with planner, selector, snapshot, normalizer, committer."""
    errors = []

    run_pipeline = getattr(mod, "run_pipeline", None)
    reset = getattr(mod, "reset", None)
    if run_pipeline is None:
        return False, ["run_pipeline function not found"]

    if reset:
        reset()

    try:
        result = run_pipeline()

        # Get the logged selection
        LOG = getattr(mod, "LOG", {})
        selected = LOG.get("selected", {})
        selected_src = selected.get("source_id", "")

        # The committed artifact must have meta.src matching selected source_id
        committed_src = result.get("meta", {}).get("src", "")

        if not selected_src:
            errors.append("invariant 1: LOG['selected'] missing source_id")
        elif committed_src != selected_src:
            errors.append(
                f"invariant 1: committed meta.src='{committed_src}', "
                f"selected source_id='{selected_src}'. "
                f"Lineage resolution failure."
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # Verify normalization did reorder (the bug only triggers when it does)
    try:
        from planner import generate_candidates
        from snapshot_store import snapshot
        from normalizer import normalize

        cands = generate_candidates()
        snap = snapshot(cands)
        normed = normalize(snap)

        # Check that normalized order differs from input order
        input_ids = [c["source_id"] for c in cands]
        normed_ids = [n["meta"]["src"] for n in normed]
        if input_ids == normed_ids:
            errors.append("precondition: normalization did not reorder — test may be vacuous")
    except Exception:
        pass  # Import may fail in concatenated module context

    # Structural
    for name in ("run_pipeline", "generate_candidates", "choose_best",
                 "snapshot", "normalize"):
        if not callable(getattr(mod, name, None)):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, ["committed matches selection by lineage", "normalization reorders"]


def test(mod):
    """Default: try L3 first, fall back to B+."""
    if hasattr(mod, "run_pipeline"):
        return test_c(mod)
    return test_b(mod)
