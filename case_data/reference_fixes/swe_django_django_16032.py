"""Reference fix for django__django-16032. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-16032'
ORACLE_FILES = ['django/db/models/fields/related_lookups.py', 'django/db/models/sql/query.py']
