"""Reference fix for django__django-16263. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-16263'
ORACLE_FILES = ['django/db/models/expressions.py', 'django/db/models/query_utils.py', 'django/db/models/sql/query.py', 'django/db/models/sql/where.py']
