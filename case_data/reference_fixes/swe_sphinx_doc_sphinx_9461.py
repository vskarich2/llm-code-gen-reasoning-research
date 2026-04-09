"""Reference fix for sphinx-doc__sphinx-9461. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'sphinx-doc__sphinx-9461'
ORACLE_FILES = ['sphinx/domains/python.py', 'sphinx/ext/autodoc/__init__.py', 'sphinx/util/inspect.py']
