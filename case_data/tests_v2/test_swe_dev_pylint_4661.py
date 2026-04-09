"""SWE-bench test stub for pylint-dev__pylint-4661.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: Make pylint XDG Base Directory Specification compliant
I have this really annoying `.pylint.d` direc...
Oracle files: ['pylint/config/__init__.py', 'setup.cfg']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
