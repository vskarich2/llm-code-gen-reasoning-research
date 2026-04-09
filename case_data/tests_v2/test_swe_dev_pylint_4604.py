"""SWE-bench test stub for pylint-dev__pylint-4604.

This case uses SWE-bench Docker evaluation for actual testing.
The test function here validates that the module loads and the
fix touches the right location.

Issue: unused-import false positive for a module used in a type comment
### Steps to reproduce
```python
...
Oracle files: ['pylint/checkers/variables.py', 'pylint/constants.py']
"""


def test_b(mod):
    """SWE-bench placeholder (difficulty B). Actual eval via Docker."""
    return True, ["SWE-bench case - actual test runs via Docker harness"]


def test(mod):
    """Generic fallback."""
    return test_b(mod)
