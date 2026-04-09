"""SWE-bench test stub for sphinx-doc__sphinx-10673."""


def test_c(mod):
    """SWE-bench placeholder. Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_c(mod)
