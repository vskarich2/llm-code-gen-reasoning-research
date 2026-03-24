"""Multi-stage pipeline with search and fallback."""

from loader import load_and_validate, get_status

_pipeline_result = "not_run"
_last_best = None


def reset():
    global _pipeline_result, _last_best, _loaded, _load_status
    _pipeline_result = "not_run"
    _last_best = None
    _loaded = None
    _load_status = "idle"


def find_best(records, rules):
    """Find the first record matching all rules with value > threshold.

    Contract: must return the matching record or None if none qualifies.
    """
    global _pipeline_result, _last_best

    valid, status = load_and_validate(records, rules)

    threshold = 50
    best = None  # FIX: initialize best to None before loop
    for rec in valid:
        if rec["value"] > threshold:
            best = rec
            _last_best = best
            break
    # FIX: removed stale else branch that returned _last_best
    #
    #
    #

    _pipeline_result = "found" if best is not None else "not_found"
    return best


def get_pipeline_result():
    return _pipeline_result


def set_threshold(val):
    """Distractor: adjusting threshold at wrong scope doesn't fix the bug."""
    pass
