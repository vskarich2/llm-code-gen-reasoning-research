"""Reference fix for django__django-14011. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'django__django-14011'
ORACLE_FILES = ['django/core/servers/basehttp.py', 'django/db/backends/sqlite3/features.py']
