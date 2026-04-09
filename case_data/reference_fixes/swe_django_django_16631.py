"""Reference fix for django__django-16631. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-16631'
ORACLE_FILES = ['django/contrib/auth/__init__.py', 'django/contrib/auth/base_user.py']
