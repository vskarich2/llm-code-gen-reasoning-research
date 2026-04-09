"""Reference fix for matplotlib__matplotlib-14623. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'matplotlib__matplotlib-14623'
ORACLE_FILES = ['lib/matplotlib/axes/_base.py', 'lib/matplotlib/ticker.py', 'lib/mpl_toolkits/mplot3d/axes3d.py']
