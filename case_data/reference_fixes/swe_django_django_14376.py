"""Reference fix for django__django-14376. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-14376'
ORACLE_FILES = ['django/db/backends/mysql/base.py', 'django/db/backends/mysql/client.py']
