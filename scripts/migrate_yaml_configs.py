#!/usr/bin/env python3
"""Migrate per-experiment YAML configs to canonical defaults.

Reads every *.yaml in core/config/config_storage/, backfills missing
canonical keys in execution/evaluation/models sections, removes dead
config (evaluation.subprocess_timeout, logging.store), and writes back.

Usage:
    .venv/bin/python scripts/migrate_yaml_configs.py
"""

import sys
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "core" / "config" / "config_storage"
SKIP_FILES = {"default.yaml"}

EXECUTION_DEFAULTS = {
    "worker_stagger_seconds": 3,
    "subprocess_timeout": 30,
    "worker_timeout_seconds": 600,
    "worker_graceful_shutdown_seconds": 30,
    "mode": "canonical",
    "keep_eval_dirs": False,
    "validate_prompts": True,
    "recovery_execution": True,
    "max_orchestrator_attempts": 10,
    "anthropic_client_timeout": 120.0,
    "anthropic_max_output_tokens": 8192,
}

EVALUATION_DEFAULTS = {
    "classifier_mode": "blind",
    "reasoning_correct_mode": "strict",
    "classifier_template": "classify_reasoning_v2",
    "classifier_schema_variant": "v2_semicolon",
    "generation_schema_variant": "v2",
}

NO_TEMP_PREFIXES_DEFAULT = ["o1", "o3", "o4", "gpt-5"]


def backfill_execution(data: dict) -> list[str]:
    """Add missing canonical keys to execution section."""
    section = data.get("execution")
    if section is None:
        return []
    added = []
    for key, default in EXECUTION_DEFAULTS.items():
        if key not in section:
            section[key] = default
            added.append(f"  + execution.{key} = {default!r}")
    return added


def backfill_evaluation(data: dict) -> list[str]:
    """Add missing canonical keys to evaluation section."""
    section = data.get("evaluation")
    if section is None:
        return []
    added = []
    for key, default in EVALUATION_DEFAULTS.items():
        if key not in section:
            section[key] = default
            added.append(f"  + evaluation.{key} = {default!r}")
    return added


def remove_eval_subprocess_timeout(data: dict) -> list[str]:
    """Remove misplaced subprocess_timeout from evaluation."""
    section = data.get("evaluation")
    if section is None:
        return []
    if "subprocess_timeout" in section:
        del section["subprocess_timeout"]
        return ["  - evaluation.subprocess_timeout (removed)"]
    return []


def backfill_no_temp_prefixes(data: dict) -> list[str]:
    """Add no_temperature_prefixes to models if missing."""
    section = data.get("models")
    if section is None:
        return []
    if not isinstance(section, dict):
        return []
    if "no_temperature_prefixes" not in section:
        section["no_temperature_prefixes"] = list(NO_TEMP_PREFIXES_DEFAULT)
        return [f"  + models.no_temperature_prefixes = {NO_TEMP_PREFIXES_DEFAULT!r}"]
    return []


def remove_logging_store(data: dict) -> list[str]:
    """Remove dead logging.store sub-section."""
    section = data.get("logging")
    if section is None:
        return []
    if not isinstance(section, dict):
        return []
    if "store" in section:
        del section["store"]
        return ["  - logging.store (removed)"]
    return []


def migrate_file(filepath: Path) -> list[str]:
    """Apply all migrations to a single YAML file.

    Returns list of change descriptions, empty if nothing changed.
    """
    with open(filepath, "r") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    changes: list[str] = []
    changes.extend(backfill_execution(data))
    changes.extend(backfill_evaluation(data))
    changes.extend(remove_eval_subprocess_timeout(data))
    changes.extend(backfill_no_temp_prefixes(data))
    changes.extend(remove_logging_store(data))
    if changes:
        with open(filepath, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return changes


def main() -> None:
    """Entry point: migrate all YAML configs and print summary."""
    if not CONFIG_DIR.is_dir():
        print(f"ERROR: config directory not found: {CONFIG_DIR}", file=sys.stderr)
        sys.exit(1)
    yaml_files = sorted(CONFIG_DIR.glob("*.yaml"))
    if not yaml_files:
        print("No YAML files found.", file=sys.stderr)
        sys.exit(1)
    total_touched = 0
    for filepath in yaml_files:
        if filepath.name in SKIP_FILES:
            print(f"SKIP  {filepath.name} (in skip list)")
            continue
        changes = migrate_file(filepath)
        if changes:
            total_touched += 1
            print(f"UPDATED  {filepath.name}")
            for line in changes:
                print(line)
        else:
            print(f"OK    {filepath.name} (no changes needed)")
    print(f"\nSummary: {total_touched} file(s) updated out of {len(yaml_files)} total.")


if __name__ == "__main__":
    main()
