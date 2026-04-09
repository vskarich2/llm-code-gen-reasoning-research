import re
from pathlib import Path
from .config import FORBIDDEN_PATTERNS
from .utils import run

def validate_diff(diff: str):
    if not diff.startswith("diff --git"):
        raise ValueError("Invalid diff")
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, diff, re.IGNORECASE):
            raise ValueError(f"Forbidden pattern: {pattern}")

def apply_patch(diff: str):
    Path("patch.diff").write_text(diff)
    run("git apply patch.diff")

def validate_code():
    run("ruff check .")
    run("pytest")
