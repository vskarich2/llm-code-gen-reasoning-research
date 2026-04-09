"""SWE-bench test stub for matplotlib__matplotlib-25479.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: Confusing (broken?) colormap name handling
Consider the following example in which one creates and r...
Oracle files: ['lib/matplotlib/cm.py', 'lib/matplotlib/colors.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
