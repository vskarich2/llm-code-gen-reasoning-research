"""Reference fix for django__django-16315. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-16315'
ORACLE_FILES = ['django/db/models/query.py', 'django/db/models/sql/compiler.py']
