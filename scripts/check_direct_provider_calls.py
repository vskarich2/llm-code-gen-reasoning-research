#!/usr/bin/env python3
"""Check that no module outside llm.py makes direct provider API calls.

All LLM calls must route through the canonical logged call path in llm.py.
Direct provider calls outside llm.py are forbidden.

Exits non-zero if any violation is found.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIR = PROJECT_ROOT / "core"

# The only file allowed to make direct provider calls
EXEMPT_FILES = {
    PROJECT_ROOT / "core" / "pipeline" / "llm.py",
    PROJECT_ROOT / "core" / "pipeline" / "llm_mock.py",
}

# Patterns indicating direct provider API usage
FORBIDDEN_PATTERNS = [
    (r'OpenAI\s*\(', "Direct OpenAI client instantiation"),
    (r'anthropic\.Anthropic\s*\(', "Direct Anthropic client instantiation"),
    (r'client\.chat\.completions', "Direct OpenAI completions call"),
    (r'client\.responses\.create', "Direct OpenAI responses call"),
    (r'client\.messages\.create', "Direct Anthropic messages call"),
    (r'_openai_call\s*\(', "Direct _openai_call invocation"),
    (r'_anthropic_call\s*\(', "Direct _anthropic_call invocation"),
]


def is_exempt(filepath: Path) -> bool:
    return filepath in EXEMPT_FILES or filepath.name.startswith("test_")


def scan_file(filepath: Path) -> list[tuple[int, str, str]]:
    violations = []
    try:
        lines = filepath.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return violations

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern, description in FORBIDDEN_PATTERNS:
            if re.search(pattern, line):
                violations.append((line_num, stripped, description))
                break
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
        print(f"DIRECT PROVIDER CALL VIOLATIONS: {len(all_violations)}")
        print()
        for rel_path, line_num, line_text, desc in all_violations:
            print(f"  {rel_path}:{line_num}: {desc}")
            print(f"    {line_text}")
            print()
        sys.exit(1)
    else:
        print("OK: no direct provider calls found outside llm.py")
        sys.exit(0)


if __name__ == "__main__":
    main()
