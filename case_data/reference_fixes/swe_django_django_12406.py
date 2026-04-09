"""Reference fix for django__django-12406. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-12406'
ORACLE_FILES = ['django/db/models/fields/related.py', 'django/forms/models.py']
