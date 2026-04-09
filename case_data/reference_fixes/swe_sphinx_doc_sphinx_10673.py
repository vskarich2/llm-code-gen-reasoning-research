"""Reference fix for sphinx-doc__sphinx-10673. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'sphinx-doc__sphinx-10673'
ORACLE_FILES = ['sphinx/directives/other.py', 'sphinx/environment/adapters/toctree.py', 'sphinx/environment/collectors/toctree.py']
