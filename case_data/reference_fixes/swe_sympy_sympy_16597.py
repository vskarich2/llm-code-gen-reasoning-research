"""Reference fix for sympy__sympy-16597. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'sympy__sympy-16597'
ORACLE_FILES = ['sympy/assumptions/ask.py', 'sympy/assumptions/ask_generated.py', 'sympy/core/assumptions.py', 'sympy/core/power.py', 'sympy/printing/tree.py', 'sympy/tensor/indexed.py']
