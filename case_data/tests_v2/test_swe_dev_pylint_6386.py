"""SWE-bench test stub for pylint-dev__pylint-6386."""


def test_c(mod):
    """SWE-bench placeholder. Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_c(mod)
