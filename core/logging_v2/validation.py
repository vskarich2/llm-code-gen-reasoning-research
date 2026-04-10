"""Pre-run validation. All checks must pass before run directory creation."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from core.logging_v2.axes import FILESYSTEM_FORBIDDEN


def validate_node_names(node_ids: list[str]) -> None:
    seen: set[str] = set()
    for nid in node_ids:
        if nid in seen:
            raise RuntimeError(
                f"Duplicate node name: {nid!r}"
            )
        seen.add(nid)
        validate_name_filesystem_safe(nid, "node")


def validate_condition_names(conditions: list[str]) -> None:
    for name in conditions:
        validate_name_filesystem_safe(name, "condition")


def validate_model_names(
    config_models: list[str], known_models: set[str],
) -> None:
    for name in config_models:
        validate_name_filesystem_safe(name, "model")
        if name not in known_models:
            raise RuntimeError(
                f"Model {name!r} not in known model set: "
                f"{sorted(known_models)}"
            )


def validate_case_ids(case_ids: list[str]) -> None:
    for cid in case_ids:
        validate_name_filesystem_safe(cid, "case_id")


def validate_name_filesystem_safe(
    value: str, label: str,
) -> None:
    for char in FILESYSTEM_FORBIDDEN:
        if char in value:
            raise RuntimeError(
                f"{label} {value!r} contains forbidden "
                f"character {char!r}"
            )


def validate_config_hash(
    config_path: Path, expected_hash: str,
) -> None:
    content = config_path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_hash:
        raise RuntimeError(
            f"Config hash mismatch: expected {expected_hash[:16]}, "
            f"got {actual[:16]}"
        )


def validate_trial_zero_indexed(trials: list[int]) -> None:
    for t in trials:
        if not isinstance(t, int) or t < 0:
            raise RuntimeError(
                f"Trial must be int >= 0, got {t!r}"
            )


def validate_run_dir_absent(target: Path) -> None:
    if target.exists():
        raise RuntimeError(
            f"Run directory already exists: {target}"
        )


def normalize_model_name(name: str, known_models: set[str]) -> str:
    """Validate model name by exact membership. No canonicalization.

    This function performs no normalization, aliasing, or case-folding.
    It only enforces that name is an exact member of known_models.
    Returns name unchanged if valid. Raises RuntimeError otherwise.
    """
    if name not in known_models:
        raise RuntimeError(f"Unknown model name: {name!r}")
    return name
