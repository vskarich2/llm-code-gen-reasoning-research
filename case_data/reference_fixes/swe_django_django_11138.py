"""Reference fix for django__django-11138. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-11138'
ORACLE_FILES = ['django/db/backends/mysql/operations.py', 'django/db/backends/oracle/operations.py', 'django/db/backends/sqlite3/base.py', 'django/db/backends/sqlite3/operations.py']
