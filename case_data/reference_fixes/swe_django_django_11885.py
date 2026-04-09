"""Reference fix for django__django-11885. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-11885'
ORACLE_FILES = ['django/contrib/admin/utils.py', 'django/db/models/deletion.py']
