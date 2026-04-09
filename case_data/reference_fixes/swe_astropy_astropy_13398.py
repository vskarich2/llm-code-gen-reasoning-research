"""Reference fix for astropy__astropy-13398. Actual fix is a multi-file patch evaluated by SWE-bench Docker."""
INSTANCE_ID = 'astropy__astropy-13398'
ORACLE_FILES = ['astropy/coordinates/builtin_frames/__init__.py', 'astropy/coordinates/builtin_frames/intermediate_rotation_transforms.py', 'astropy/coordinates/builtin_frames/itrs.py', 'astropy/coordinates/builtin_frames/itrs_observed_transforms.py']
