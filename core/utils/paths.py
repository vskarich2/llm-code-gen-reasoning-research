"""Centralized path resolution — single source of truth for repo layout.

All test and infrastructure code must use these functions instead of
constructing paths from __file__ or hardcoded strings.
"""

from __future__ import annotations

from pathlib import Path

PYPROJECT_MARKER = "pyproject.toml"


def get_repo_root() -> Path:
    """Walk up from this file until pyproject.toml is found."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / PYPROJECT_MARKER).exists():
            return parent
    raise RuntimeError(
        f"Could not find {PYPROJECT_MARKER} in any parent of "
        f"{Path(__file__).resolve()}"
    )


def get_case_data_dir() -> Path:
    return get_repo_root() / "case_data"


def get_cases_v2_path() -> Path:
    return get_case_data_dir() / "cases_v2.json"


def get_reference_fixes_dir() -> Path:
    return get_case_data_dir() / "reference_fixes"


def get_config_dir() -> Path:
    return get_repo_root() / "core" / "config" / "config_storage"
