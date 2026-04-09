"""Reference fix for django__django-13121. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-13121'
ORACLE_FILES = ['django/db/backends/base/operations.py', 'django/db/backends/mysql/operations.py', 'django/db/backends/sqlite3/operations.py', 'django/db/models/expressions.py']
