"""Reference fix for django__django-16560. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-16560'
ORACLE_FILES = ['django/contrib/postgres/constraints.py', 'django/db/models/constraints.py']
