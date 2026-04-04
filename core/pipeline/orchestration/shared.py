"""Shared utilities used by both orchestrator and runner.

These functions are needed by both processes independently
(orchestrator spawns runner as a subprocess, not a function call).
"""

from __future__ import annotations

import json
import time
from pathlib import Path


# ============================================================
# CASE LOADING
# ============================================================

def _compute_logical_key(rel_path: str) -> str:
    """Derive prompt-facing key from storage path. Returns bare filename.

    Input:  "code_snippets_v2/alias_config_b/config.py"
    Output: "config.py"
    """
    return Path(rel_path).name


def validate_import_consistency(case: dict) -> None:
    """Preflight: verify case files have consistent import structure."""
    import ast
    from collections import Counter

    file_paths = case["code_files"]
    cid = case["id"]

    parents = set(str(Path(f).parent) for f in file_paths)
    assert len(parents) == 1, (
        f"Case {cid}: files span multiple directories: {parents}."
    )

    basenames = [Path(f).name for f in file_paths]
    dupes = [b for b, c in Counter(basenames).items() if c > 1]
    assert not dupes, (
        f"Case {cid}: duplicate basenames: {dupes}."
    )

    sibling_modules = {Path(f).stem for f in file_paths}
    for rel_path in file_paths:
        content = case["code_files_contents"].get(rel_path, "")
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    raise ValueError(
                        f"Case {cid}: {rel_path} uses relative import "
                        f"(level={node.level}). Not supported."
                    )
                if node.module and "." in node.module:
                    base = node.module.split(".")[0]
                    if base in sibling_modules:
                        raise ValueError(
                            f"Case {cid}: {rel_path} uses package-qualified "
                            f"import '{node.module}'. Use flat sibling import."
                        )


def load_cases(case_id: str, cases_file: str) -> list[dict]:
    """Load and validate cases from JSON file."""
    from core.config.paths import PROJECT_ROOT
    cases_path = PROJECT_ROOT / cases_file
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    for case in cases:
        code_files = {}
        for rel_path in case["code_files"]:
            full_path = PROJECT_ROOT / "case_data" / rel_path
            content = full_path.read_text(encoding="utf-8").strip()
            assert content, (
                f"PREFLIGHT: Empty file {rel_path} in case {case['id']}."
            )
            code_files[rel_path] = content
        case["code_files_contents"] = code_files
        logical_keys = {}
        for rp, content in code_files.items():
            lk = _compute_logical_key(rp)
            if lk in logical_keys:
                raise RuntimeError(
                    f"Logical key collision: '{lk}' from '{rp}' "
                    f"in case {case['id']}"
                )
            logical_keys[lk] = content
        case["logical_file_keys"] = logical_keys
        validate_import_consistency(case)
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
        if not cases:
            raise ValueError(f"No case with id={case_id!r}")
    return cases


# ============================================================
# PREFLIGHT
# ============================================================

def preflight_verify_tests(cases: list[dict]) -> None:
    """Verify every case has a resolvable test function BEFORE running."""
    from core.pipeline.execution.test_loader import _load_v2_test

    missing = []
    for case in cases:
        cid = case["id"]
        test_fn = _load_v2_test(case)
        if test_fn is None:
            missing.append(cid)

    if missing:
        raise RuntimeError(
            f"PREFLIGHT FAILURE: {len(missing)} case(s) have NO test function. "
            f"Missing: {missing}"
        )


# ============================================================
# DIRECTORY MANAGEMENT
# ============================================================

def create_run_timestamp_dir(run_dir: Path, run_id: str = "") -> Path:
    """Create a uniquely-named subdirectory inside run_dir.

    Format: YYYY-MM-DD_HH-MM-SS_{run_id} (sortable, collision-free).
    """
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    name = f"{timestamp}_{run_id}" if run_id else timestamp
    ts_dir = run_dir / name
    ts_dir.mkdir(parents=True, exist_ok=False)
    return ts_dir
