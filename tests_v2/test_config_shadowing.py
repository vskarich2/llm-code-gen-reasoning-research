"""Tests for config_shadowing (L3 — structural vs contingent cause).

Invariant: both request and background paths must use timeout=30.
"""


def test(mod):
    """Non-diagnostic: reports wrong timeout, does not identify config layer."""
    result = mod.run_system_check()
    req = result["request"]["timeout"]
    bg = result["background"]["timeout"]

    if req != 30:
        return False, [f"request timeout incorrect: {req}"]
    if bg != 30:
        return False, [f"background timeout incorrect: {bg}"]
    return True, ["all timeouts correct"]
