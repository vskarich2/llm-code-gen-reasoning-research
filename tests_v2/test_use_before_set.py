"""Tests for use_before_set family (edge_case_omission).

Invariant: variables must reflect current call's state, not prior state.
"""


def test_a(mod):
    """Level A: transform([]) must return empty list, not stale data."""
    # Reset module state
    if hasattr(mod, "_last_result"):
        mod._last_result = []

    # First call with real data
    r1 = mod.transform([1, 2, 3])
    # Second call with empty data
    r2 = mod.transform([])

    if r2 != []:
        return False, [
            f"transform([]) returned {r2}, expected [] " f"(stale data from previous call leaked)"
        ]

    return True, ["transform returns fresh empty list for empty input"]


def test_b(mod):
    """Level B: status must reflect current load, not previous."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_status"):
        mod._status = "idle"
    if hasattr(mod, "_load_status"):
        mod._load_status = "idle"
    if hasattr(mod, "_data"):
        mod._data = None
    if hasattr(mod, "_loaded"):
        mod._loaded = None

    # First call with real data
    r1 = mod.run_pipeline([10, 20, 30])
    # Second call with empty data
    r2 = mod.run_pipeline([])

    if r2["status"] == "loaded":
        return False, [
            f"status is 'loaded' after empty input — " f"stale status from previous call leaked"
        ]

    if r2["count"] != 0:
        return False, [f"count={r2['count']} after empty input, expected 0"]

    return True, ["status correctly reflects empty input"]


def test_c(mod):
    """Level C: find_best must return None when no records qualify."""
    # Reset module state
    if hasattr(mod, "reset"):
        mod.reset()
    if hasattr(mod, "_last_best"):
        mod._last_best = None
    if hasattr(mod, "_pipeline_result"):
        mod._pipeline_result = "not_run"

    # First call: record that exceeds threshold (50)
    high_records = [{"id": "h1", "value": 100}]
    r1 = mod.find_best(high_records, ["non_negative"])

    # Second call: only low-value records (below threshold)
    low_records = [{"id": "l1", "value": 10}, {"id": "l2", "value": 20}]
    r2 = mod.find_best(low_records, ["non_negative"])

    if r2 is not None:
        return False, [
            f"find_best returned {r2} for below-threshold records, "
            f"expected None (stale result from previous call leaked)"
        ]

    return True, ["find_best returns None when no records qualify"]
