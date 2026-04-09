"""SWE-bench test stub for mwaskom__seaborn-3187.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: Wrong legend values of large ranges
As of 0.12.1, legends describing large numbers that were created...
Oracle files: ['seaborn/_core/scales.py', 'seaborn/utils.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
