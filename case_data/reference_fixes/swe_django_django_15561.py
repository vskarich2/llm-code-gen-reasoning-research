"""Reference fix for django__django-15561. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-15561'
ORACLE_FILES = ['django/db/backends/base/schema.py', 'django/db/models/fields/__init__.py']
