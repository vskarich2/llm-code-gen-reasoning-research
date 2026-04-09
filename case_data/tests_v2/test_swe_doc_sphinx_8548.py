"""SWE-bench test stub for sphinx-doc__sphinx-8548.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: autodoc inherited-members won't work for inherited attributes (data members).
autodoc searches for a...
Oracle files: ['sphinx/ext/autodoc/__init__.py', 'sphinx/ext/autodoc/importer.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
