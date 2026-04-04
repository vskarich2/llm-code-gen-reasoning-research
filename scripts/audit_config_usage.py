#!/usr/bin/env python3
"""Forensic config audit: detect hardcoded defaults, unused fields, duplicates.

Usage:
    .venv/bin/python scripts/audit_config_usage.py
"""

import ast
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CORE_DIR = PROJECT / "core"

# ── Known config dataclass fields (source of truth: experiment_config.py) ──

EXECUTION_FIELDS = {
    "num_workers", "worker_stagger_seconds", "token_budgets",
    "import_summary", "file_ordering", "output_format", "mode",
    "keep_eval_dirs", "subprocess_timeout", "worker_timeout_seconds",
    "validate_prompts", "worker_graceful_shutdown_seconds",
}

EVALUATION_FIELDS = {
    "leg_enabled", "failure_classification_enabled", "alignment_enabled",
    "classifier_mode", "reasoning_correct_mode", "classifier_template",
    "classifier_schema_variant", "generation_schema_variant",
}

LOGGING_FIELDS = {
    "level", "output_dir", "store_raw_prompts", "store_raw_outputs",
    "redis_enabled", "redis_url", "redis_stream_maxlen",
}

RETRY_FIELDS = {
    "enabled", "max_attempts", "include_test_output", "include_critique",
    "include_previous_code", "stop_on_pass", "stop_on_stagnation",
    "stagnation_window", "similarity_threshold", "score_epsilon",
    "persistence_escalation_count", "max_iteration_seconds",
    "max_total_seconds",
}


def scan_hardcoded_defaults(py_files):
    """Find .get("key", <literal>) and getattr(..., <literal>) patterns."""
    issues = []
    get_pat = re.compile(
        r"""\.get\(\s*["'](\w+)["']\s*,\s*(.+?)\s*\)"""
    )
    getattr_pat = re.compile(
        r"""getattr\(\s*[\w.]+\s*,\s*["'](\w+)["']\s*,\s*(.+?)\s*\)"""
    )
    hasattr_pat = re.compile(
        r"""hasattr\(\s*(config[\w.]*)\s*,\s*["'](\w+)["']\s*\)"""
    )

    for py_file in py_files:
        rel = py_file.relative_to(PROJECT)
        text = py_file.read_text(errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for m in get_pat.finditer(line):
                key, default = m.group(1), m.group(2).strip()
                if default not in ("None", "none", "{}", "[]", "()"):
                    issues.append({
                        "type": "HARDCODED_DEFAULT_GET",
                        "file": str(rel),
                        "line": i,
                        "key": key,
                        "default": default,
                        "code": stripped,
                    })

            for m in getattr_pat.finditer(line):
                key, default = m.group(1), m.group(2).strip()
                if default not in ("None", "none"):
                    issues.append({
                        "type": "HARDCODED_DEFAULT_GETATTR",
                        "file": str(rel),
                        "line": i,
                        "key": key,
                        "default": default,
                        "code": stripped,
                    })

            for m in hasattr_pat.finditer(line):
                obj, attr = m.group(1), m.group(2)
                issues.append({
                    "type": "HASATTR_GUARD",
                    "file": str(rel),
                    "line": i,
                    "key": f"{obj}.{attr}",
                    "default": "(implicit None/skip)",
                    "code": stripped,
                })

    return issues


def scan_module_constants(py_files):
    """Find module-level ALL_CAPS constants that look like config values."""
    issues = []
    const_pat = re.compile(r"^(MAX_\w+|_?[A-Z][A-Z_]+)\s*=\s*(\d+\.?\d*|True|False|\"[^\"]+\")")

    skip_files = {"constants.py", "paths.py", "__init__.py"}

    for py_file in py_files:
        if py_file.name in skip_files:
            continue
        rel = py_file.relative_to(PROJECT)
        text = py_file.read_text(errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            m = const_pat.match(line.strip())
            if m:
                name, value = m.group(1), m.group(2)
                if name.startswith("__"):
                    continue
                issues.append({
                    "type": "MODULE_CONSTANT",
                    "file": str(rel),
                    "line": i,
                    "key": name,
                    "default": value,
                    "code": line.strip(),
                })

    return issues


def scan_unused_config_fields(py_files):
    """Check which config dataclass fields are never accessed in pipeline code."""
    all_code = ""
    for py_file in py_files:
        if "experiment_config.py" in str(py_file):
            continue
        all_code += py_file.read_text(errors="replace") + "\n"

    unused = []
    for section, fields in [
        ("ExecutionConfig", EXECUTION_FIELDS),
        ("EvaluationConfig", EVALUATION_FIELDS),
        ("LoggingConfig", LOGGING_FIELDS),
    ]:
        for field in sorted(fields):
            # Check if field name appears in pipeline code
            if field not in all_code:
                unused.append({
                    "type": "UNUSED_FIELD",
                    "section": section,
                    "field": field,
                })

    return unused


def scan_try_except_fallbacks(py_files):
    """Find try/except blocks that silently return fallback values."""
    issues = []
    for py_file in py_files:
        rel = py_file.relative_to(PROJECT)
        text = py_file.read_text(errors="replace")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("except") and i + 1 < len(lines):
                next_lines = "\n".join(
                    l.strip() for l in lines[i + 1:i + 4]
                )
                if re.search(r"return\s+[\d\"'\({\[]", next_lines):
                    issues.append({
                        "type": "SILENT_FALLBACK",
                        "file": str(rel),
                        "line": i + 1,
                        "code": stripped,
                        "fallback": next_lines.split("\n")[0].strip(),
                    })

    return issues


def scan_dead_functions(py_files):
    """Find functions defined in llm.py that are never called elsewhere."""
    llm_file = CORE_DIR / "pipeline" / "llm.py"
    if not llm_file.exists():
        return []

    tree = ast.parse(llm_file.read_text())
    defined = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("__"):
            defined.append(node.name)

    all_code = ""
    for py_file in py_files:
        if py_file == llm_file:
            continue
        all_code += py_file.read_text(errors="replace") + "\n"

    issues = []
    for fn in defined:
        # Count occurrences outside the defining file
        pattern = re.compile(rf"\b{re.escape(fn)}\b")
        if not pattern.search(all_code):
            issues.append({
                "type": "DEAD_FUNCTION",
                "file": str(llm_file.relative_to(PROJECT)),
                "function": fn,
            })

    return issues


def scan_forbidden_config_patterns(py_files):
    """Check for patterns that must not exist after config repair."""
    issues = []
    pipeline_dir = CORE_DIR / "pipeline"

    for py_file in py_files:
        if "__pycache__" in str(py_file):
            continue
        rel = py_file.relative_to(PROJECT)
        text = py_file.read_text(errors="replace")

        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            # No getattr(config...) in pipeline code
            if str(py_file).startswith(str(pipeline_dir)):
                if re.search(r"getattr\(config", stripped):
                    issues.append({
                        "type": "FORBIDDEN_GETATTR_CONFIG",
                        "file": str(rel),
                        "line": i,
                        "code": stripped[:100],
                    })
                # No hasattr(config...) except in preflight.py
                if "preflight" not in py_file.name:
                    if re.search(r"hasattr\(config", stripped):
                        issues.append({
                            "type": "FORBIDDEN_HASATTR_CONFIG",
                            "file": str(rel),
                            "line": i,
                            "code": stripped[:100],
                        })

        # No _KNOWN_*_FIELDS in experiment_config.py
        if py_file.name == "experiment_config.py":
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(r"_KNOWN_\w+_FIELDS\s*=", line):
                    issues.append({
                        "type": "FORBIDDEN_MANUAL_ALLOWLIST",
                        "file": str(rel),
                        "line": i,
                        "code": line.strip()[:100],
                    })

    # No MAX_ module constants in orchestration (except _SIGKILL)
    orch_dir = pipeline_dir / "orchestration"
    for py_file in orch_dir.glob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        rel = py_file.relative_to(PROJECT)
        for i, line in enumerate(py_file.read_text().splitlines(), 1):
            if re.match(r"^MAX_\w+\s*=", line.strip()):
                issues.append({
                    "type": "FORBIDDEN_MODULE_CONSTANT",
                    "file": str(rel),
                    "line": i,
                    "code": line.strip()[:100],
                })

    return issues


def main():
    py_files = sorted(CORE_DIR.rglob("*.py"))
    # Exclude __pycache__
    py_files = [f for f in py_files if "__pycache__" not in str(f)]

    print("=" * 70)
    print("FORENSIC CONFIG AUDIT")
    print("=" * 70)

    # 1. Hardcoded defaults
    hc = scan_hardcoded_defaults(py_files)
    print(f"\n{'='*70}")
    print(f"1. HARDCODED DEFAULTS ({len(hc)} found)")
    print(f"{'='*70}")
    for issue in hc:
        print(f"  [{issue['type']}] {issue['file']}:{issue['line']}")
        print(f"    key={issue['key']} default={issue['default']}")
        print(f"    {issue['code'][:100]}")
        print()

    # 2. Module constants
    mc = scan_module_constants(py_files)
    print(f"\n{'='*70}")
    print(f"2. MODULE-LEVEL CONSTANTS ({len(mc)} found)")
    print(f"{'='*70}")
    for issue in mc:
        print(f"  [{issue['type']}] {issue['file']}:{issue['line']}")
        print(f"    {issue['key']} = {issue['default']}")
        print()

    # 3. Unused config fields
    uf = scan_unused_config_fields(py_files)
    print(f"\n{'='*70}")
    print(f"3. UNUSED CONFIG FIELDS ({len(uf)} found)")
    print(f"{'='*70}")
    for issue in uf:
        print(f"  [{issue['type']}] {issue['section']}.{issue['field']}")
    print()

    # 4. Silent fallbacks
    sf = scan_try_except_fallbacks(py_files)
    print(f"\n{'='*70}")
    print(f"4. SILENT TRY/EXCEPT FALLBACKS ({len(sf)} found)")
    print(f"{'='*70}")
    for issue in sf:
        print(f"  [{issue['type']}] {issue['file']}:{issue['line']}")
        print(f"    {issue['code']}")
        print(f"    → {issue.get('fallback', '')}")
        print()

    # 5. Dead functions in llm.py
    df = scan_dead_functions(py_files)
    print(f"\n{'='*70}")
    print(f"5. DEAD FUNCTIONS in llm.py ({len(df)} found)")
    print(f"{'='*70}")
    for issue in df:
        print(f"  [{issue['type']}] {issue['file']}::{issue['function']}()")
    print()

    # 6. Forbidden config patterns (post-repair checks)
    fp = scan_forbidden_config_patterns(py_files)
    print(f"\n{'='*70}")
    print(f"6. FORBIDDEN CONFIG PATTERNS ({len(fp)} found)")
    print(f"{'='*70}")
    for issue in fp:
        print(f"  [{issue['type']}] {issue['file']}:{issue['line']}")
        print(f"    {issue['code']}")
        print()

    # Summary
    total = len(hc) + len(mc) + len(uf) + len(sf) + len(df) + len(fp)
    print(f"\n{'='*70}")
    print(f"SUMMARY: {total} total issues")
    print(f"{'='*70}")
    print(f"  Hardcoded defaults:       {len(hc)}")
    print(f"  Module constants:         {len(mc)}")
    print(f"  Unused config fields:     {len(uf)}")
    print(f"  Silent fallbacks:         {len(sf)}")
    print(f"  Dead functions:           {len(df)}")
    print(f"  Forbidden patterns:       {len(fp)}")

    # Forbidden patterns are hard failures
    if len(fp) > 0:
        print(f"\n  HARD FAIL: {len(fp)} forbidden config patterns detected")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
