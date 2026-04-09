"""Reference fix for matplotlib__matplotlib-25775. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'matplotlib__matplotlib-25775'
ORACLE_FILES = ['lib/matplotlib/backends/backend_agg.py', 'lib/matplotlib/backends/backend_cairo.py', 'lib/matplotlib/text.py']
