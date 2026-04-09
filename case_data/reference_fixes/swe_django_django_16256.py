"""Reference fix for django__django-16256. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-16256'
ORACLE_FILES = ['django/contrib/contenttypes/fields.py', 'django/db/models/fields/related_descriptors.py']
