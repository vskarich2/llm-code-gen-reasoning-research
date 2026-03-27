"""Canonical stdlib module list for T3 benchmark.

Single source of truth. Imported by parse.py and validate_cases_v2.py.
"""

STDLIB_MODULES = frozenset(
    {
        "os",
        "sys",
        "re",
        "json",
        "time",
        "random",
        "hashlib",
        "threading",
        "math",
        "functools",
        "itertools",
        "collections",
        "typing",
        "pathlib",
        "dataclasses",
        "abc",
        "copy",
        "tempfile",
        "importlib",
        "textwrap",
        # Additional modules used by cases but previously missing from parse.py:
        "datetime",
        "enum",
        "logging",
        "io",
        "string",
    }
)
