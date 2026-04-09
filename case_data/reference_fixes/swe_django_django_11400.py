"""Reference fix for django__django-11400. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-11400'
ORACLE_FILES = ['django/contrib/admin/filters.py', 'django/db/models/fields/__init__.py', 'django/db/models/fields/reverse_related.py']
