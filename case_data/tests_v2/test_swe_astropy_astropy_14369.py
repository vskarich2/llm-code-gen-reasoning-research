"""SWE-bench test stub for astropy__astropy-14369."""


def test_b(mod):
    """SWE-bench placeholder. Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
