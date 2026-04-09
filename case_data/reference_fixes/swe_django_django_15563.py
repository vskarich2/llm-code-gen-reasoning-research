"""Reference fix for django__django-15563. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-15563'
ORACLE_FILES = ['django/db/models/sql/compiler.py', 'django/db/models/sql/subqueries.py']
