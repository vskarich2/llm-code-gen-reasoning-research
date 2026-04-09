"""Reference fix for sympy__sympy-20438. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'sympy__sympy-20438'
ORACLE_FILES = ['sympy/core/relational.py', 'sympy/sets/handlers/comparison.py', 'sympy/sets/handlers/issubset.py']
