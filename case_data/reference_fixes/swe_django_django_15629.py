"""Reference fix for django__django-15629. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-15629'
ORACLE_FILES = ['django/db/backends/base/schema.py', 'django/db/backends/oracle/features.py', 'django/db/backends/sqlite3/schema.py', 'django/db/models/fields/related.py']
