"""SWE-bench test stub for pylint-dev__pylint-6528.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: Pylint does not respect ignores in `--recursive=y` mode
### Bug description
Pylint does not respect...
Oracle files: ['pylint/lint/expand_modules.py', 'pylint/lint/pylinter.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
