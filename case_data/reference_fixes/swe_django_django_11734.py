"""Reference fix for django__django-11734. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-11734'
ORACLE_FILES = ['django/db/models/fields/__init__.py', 'django/db/models/fields/related_lookups.py', 'django/db/models/sql/query.py']
