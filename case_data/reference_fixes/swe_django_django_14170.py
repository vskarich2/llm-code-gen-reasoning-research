"""Reference fix for django__django-14170. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-14170'
ORACLE_FILES = ['django/db/backends/base/operations.py', 'django/db/models/lookups.py']
