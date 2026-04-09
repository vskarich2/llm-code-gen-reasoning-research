"""Reference fix for django__django-13195. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-13195'
ORACLE_FILES = ['django/contrib/messages/storage/cookie.py', 'django/contrib/sessions/middleware.py', 'django/http/response.py']
