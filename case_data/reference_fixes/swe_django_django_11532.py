"""Reference fix for django__django-11532. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-11532'
ORACLE_FILES = ['django/core/mail/message.py', 'django/core/mail/utils.py', 'django/core/validators.py', 'django/utils/encoding.py', 'django/utils/html.py']
