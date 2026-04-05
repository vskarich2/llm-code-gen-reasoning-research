"""Tests for partial_system_correctness family.

Invariant: pipeline must preserve numeric meaning across stages.
Bug: to_internal truncates to int (dollars) but aggregate divides by 100 (expects cents).
"""


def test(mod):
    errors = []

    process = getattr(mod, "process", None)
    if process is None:
        return False, ["process function not found"]

    # ── Invariant 1: decimal inputs preserve value ──
    # [1.50, 2.50] → avg should be 2.00
    # Buggy: to_internal(1.50)=1, to_internal(2.50)=2 → avg cents = 1.5 → /100 = 0.015
    # Fixed: to_internal(1.50)=150, to_internal(2.50)=250 → avg cents = 200 → /100 = 2.0
    try:
        result = process([1.50, 2.50])
        if abs(result - 2.0) > 0.01:
            errors.append(
                f"invariant 1: process([1.50, 2.50])={result}, expected 2.0"
            )
    except Exception as e:
        errors.append(f"invariant 1 raised: {e}")

    # ── Invariant 2: single decimal value ──
    # [3.75] → should return 3.75
    try:
        result2 = process([3.75])
        if abs(result2 - 3.75) > 0.01:
            errors.append(
                f"invariant 2: process([3.75])={result2}, expected 3.75"
            )
    except Exception as e:
        errors.append(f"invariant 2 raised: {e}")

    # ── Invariant 3: negative values filtered ──
    try:
        result3 = process([5.00, -1.00, 10.00])
        if abs(result3 - 7.50) > 0.01:
            errors.append(
                f"invariant 3: process([5.00, -1.00, 10.00])={result3}, expected 7.50"
            )
    except Exception as e:
        errors.append(f"invariant 3 raised: {e}")

    # ── Invariant 4: anti-hardcoding — different values ──
    try:
        result4 = process([0.99, 1.01])
        if abs(result4 - 1.0) > 0.01:
            errors.append(
                f"anti-hardcoding: process([0.99, 1.01])={result4}, expected 1.0"
            )
    except Exception as e:
        errors.append(f"anti-hardcoding raised: {e}")

    # ── Structural ──
    for name in ("process", "validate", "to_internal", "aggregate"):
        if not hasattr(mod, name):
            errors.append(f"structural: {name} not found")

    if errors:
        return False, errors
    return True, [
        "decimal values preserved",
        "single value correct",
        "negative filtering works",
        "anti-hardcoding passed",
    ]
