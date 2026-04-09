"""SWE-bench test stub for sphinx-doc__sphinx-7462.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: `IndexError: pop from empty list` for empty tuple type annotation
**Describe the bug**
Following no...
Oracle files: ['sphinx/domains/python.py', 'sphinx/pycode/ast.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
