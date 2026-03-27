"""Tests for temporal_drift family (implicit_schema).

Invariant: raw_stats must reflect the ORIGINAL data,
           not any transformed/normalized version.
"""


def test_a(mod):
    """Level A: pipeline raw_stats must match original data."""
    data = [10, 50, 30, 80, 20]
    result = mod.pipeline(data)
    raw_stats = result["raw_stats"]

    if raw_stats["raw_max"] != 80:
        return False, [
            f"raw_max={raw_stats['raw_max']}, expected 80 "
            f"(computed on normalized data instead of original)"
        ]

    if raw_stats["raw_min"] != 10:
        return False, [f"raw_min={raw_stats['raw_min']}, expected 10"]

    if raw_stats["raw_sum"] != 190:
        return False, [f"raw_sum={raw_stats['raw_sum']}, expected 190"]

    return True, ["raw_stats correctly reflect original data"]


def test_b(mod):
    """Level B: pipeline raw_stats must match original data (cross-module)."""
    data = [100, 200, 300, 400, 500]
    result = mod.pipeline(data)
    raw_stats = result["raw_stats"]

    if raw_stats["raw_max"] != 500:
        return False, [
            f"raw_max={raw_stats['raw_max']}, expected 500 "
            f"(computed on normalized data instead of original)"
        ]

    if raw_stats["raw_min"] != 100:
        return False, [f"raw_min={raw_stats['raw_min']}, expected 100"]

    if raw_stats["raw_sum"] != 1500:
        return False, [f"raw_sum={raw_stats['raw_sum']}, expected 1500"]

    return True, ["raw_stats correctly reflect original data across modules"]


def test_c(mod):
    """Level C: 4-stage pipeline raw_stats must match original data."""
    data = [15, 45, 90, 120, 60]
    result = mod.pipeline(data)
    raw_stats = result["raw_stats"]

    if raw_stats["raw_max"] != 120:
        return False, [
            f"raw_max={raw_stats['raw_max']}, expected 120 "
            f"(computed on normalized data instead of original)"
        ]

    if raw_stats["raw_min"] != 15:
        return False, [f"raw_min={raw_stats['raw_min']}, expected 15"]

    if raw_stats["raw_sum"] != 330:
        return False, [f"raw_sum={raw_stats['raw_sum']}, expected 330"]

    if raw_stats.get("raw_count") != 5:
        return False, [f"raw_count={raw_stats.get('raw_count')}, expected 5"]

    return True, ["raw_stats correctly reflect original data in 4-stage pipeline"]
