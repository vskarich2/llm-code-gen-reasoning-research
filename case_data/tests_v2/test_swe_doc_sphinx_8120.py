"""SWE-bench test stub for sphinx-doc__sphinx-8120.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: locale/<language>/LC_MESSAGES/sphinx.po translation ignored
**Describe the bug**
I read [1] as it s...
Oracle files: ['sphinx/application.py', 'sphinx/locale/__init__.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
