#!/usr/bin/env python3
"""Check for forbidden hardcoded repo-layout path literals in production code.

Scans all .py files under core/ (excluding allowed exceptions).
Exits non-zero if any forbidden pattern is found.

Run as mandatory pre-merge check on PRs touching core/.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCAN_DIR = PROJECT_ROOT / "core"

# Files exempt from scanning
EXEMPT_FILES = {
    PROJECT_ROOT / "core" / "config" / "paths.py",
    PROJECT_ROOT / "core" / "harness" / "run_case.py",
}

# Patterns that indicate hardcoded repo-layout paths
FORBIDDEN_PATTERNS = [
    (r'Path\s*\(\s*["\']core/', "Path constructor with 'core/' literal"),
    (r'Path\s*\(\s*["\']case_data/', "Path constructor with 'case_data/' literal"),
    (r'["\']tests_v2[/"\']', "'tests_v2' path fragment (excluding module imports)"),
    (r'["\']code_snippets', "'code_snippets' path fragment"),
    (r'Path\s*\(\s*["\']prompts/', "Path constructor with 'prompts/' literal"),
    (r'Path\s*\(\s*["\']components/', "Path constructor with 'components/' literal"),
    (r'["\']reference_fixes[/"\']', "'reference_fixes' path fragment"),
    (r'["\']ast_specs', "'ast_specs' path fragment"),
]

# Patterns to exclude (false positives)
EXCLUDE_PATTERNS = [
    r'^\s*#',           # comments
    r'^\s*["\'].*["\']', # standalone string literals (docstrings, etc.)
    r'tests_v2\.test_',  # module import pattern (allowed)
]


def is_exempt(filepath: Path) -> bool:
    return filepath in EXEMPT_FILES or filepath.name.startswith("test_")


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Returns list of (line_number, line_text, violation_description)."""
    violations = []
    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return violations

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith("#"):
            continue

        for pattern, description in FORBIDDEN_PATTERNS:
            if re.search(pattern, line):
                # Check exclusions
                excluded = False
                for exc in EXCLUDE_PATTERNS:
                    if re.search(exc, stripped):
                        excluded = True
                        break
                # Special: allow tests_v2.test_ as module import
                if "tests_v2" in pattern and "tests_v2.test_" in line:
                    excluded = True

                if not excluded:
                    violations.append((line_num, stripped, description))
                    break  # one violation per line is enough

    return violations


def main():
    all_violations = []

    for py_file in sorted(SCAN_DIR.rglob("*.py")):
        if is_exempt(py_file):
            continue
        violations = scan_file(py_file)
        for line_num, line_text, desc in violations:
            rel_path = py_file.relative_to(PROJECT_ROOT)
            all_violations.append((rel_path, line_num, line_text, desc))

    if all_violations:
        print(f"FORBIDDEN PATH VIOLATIONS: {len(all_violations)}")
        print()
        for rel_path, line_num, line_text, desc in all_violations:
            print(f"  {rel_path}:{line_num}: {desc}")
            print(f"    {line_text}")
            print()
        sys.exit(1)
    else:
        print("OK: no forbidden path literals found in core/")
        sys.exit(0)


if __name__ == "__main__":
    main()
