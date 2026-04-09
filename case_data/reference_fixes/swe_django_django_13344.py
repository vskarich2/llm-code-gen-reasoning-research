"""Reference fix for django__django-13344. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-13344'
ORACLE_FILES = ['django/contrib/sessions/middleware.py', 'django/middleware/cache.py', 'django/middleware/security.py']
