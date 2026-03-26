"""Config loader, validator, and frozen dataclasses for T3 benchmark.

Loads experiment.yaml, validates strictly, and produces an immutable ExperimentConfig.
"""

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from constants import (
    VALID_CONDITIONS, RETRY_CONDITIONS, MULTISTEP_CONDITIONS, SIMPLE_CONDITIONS,
    CURRENT_CONFIG_VERSION,
)

_log = logging.getLogger("t3.config")

BASE_DIR = Path(__file__).parent


# ============================================================
# EXCEPTIONS
# ============================================================

class ConfigError(Exception):
    """Raised on any config validation failure."""
    pass


# ============================================================
# FROZEN DATACLASSES
# ============================================================

@dataclass(frozen=True)
class ConditionConfig:
    """Config for a single experimental condition."""
    template: str
    retry_template: str | None = None
    next_template: str | None = None


@dataclass(frozen=True)
class RetryConfig:
    enabled: bool
    max_steps: int
    strategy: str


@dataclass(frozen=True)
class ExecutionConfig:
    parallel: int
    cases_file: str
    timeout_total_seconds: int
    timeout_per_step_seconds: int


@dataclass(frozen=True)
class LoggingConfig:
    run_dir_pattern: str
    log_resolved_config: bool


@dataclass(frozen=True)
class ExperimentConfig:
    version: int
    name: str
    models: tuple[str, ...]
    conditions: dict[str, ConditionConfig]
    retry: RetryConfig
    execution: ExecutionConfig
    logging: LoggingConfig


# ============================================================
# SECTION SCHEMAS
# ============================================================

REQUIRED_TOP_KEYS = {"experiment", "conditions", "retry", "execution", "logging"}

EXPERIMENT_REQUIRED = {"version": int, "name": str, "models": list}

RETRY_REQUIRED = {"enabled": bool, "max_steps": int, "strategy": str}
RETRY_STRATEGY_VALUES = {"linear"}

EXECUTION_REQUIRED = {
    "parallel": int, "cases_file": str,
    "timeout_total_seconds": int, "timeout_per_step_seconds": int,
}

LOGGING_REQUIRED = {"run_dir_pattern": str, "log_resolved_config": bool}

CONDITION_ALLOWED_KEYS = {"template", "retry_template", "next_template"}


# ============================================================
# VALIDATION HELPERS
# ============================================================

def _validate_section(raw: dict, section_name: str, required: dict[str, type]) -> None:
    """Validate a config section: require keys, check types, reject unknown."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{section_name} must be a dict")
    for key, expected_type in required.items():
        if key not in raw:
            raise ConfigError(f"{section_name}.{key} is required")
        if not isinstance(raw[key], expected_type):
            raise ConfigError(
                f"{section_name}.{key} must be {expected_type.__name__}, "
                f"got {type(raw[key]).__name__}"
            )
    unknown = raw.keys() - required.keys()
    if unknown:
        raise ConfigError(f"Unknown keys in {section_name}: {unknown}")


def _validate_conditions(conditions_raw: dict) -> dict[str, ConditionConfig]:
    """Validate conditions section and build ConditionConfig objects."""
    from templates import TEMPLATE_REGISTRY

    if not isinstance(conditions_raw, dict) or len(conditions_raw) == 0:
        raise ConfigError("conditions must be a non-empty dict")

    result = {}
    for cond_name, cond_raw in conditions_raw.items():
        # a) Validate condition name
        if cond_name not in VALID_CONDITIONS:
            raise ConfigError(
                f"conditions.{cond_name} is not a valid condition. "
                f"Valid: {sorted(VALID_CONDITIONS)}"
            )

        # b) Validate structure
        if not isinstance(cond_raw, dict):
            raise ConfigError(f"conditions.{cond_name} must be a dict")

        # c) Require 'template' key
        if "template" not in cond_raw:
            raise ConfigError(f"conditions.{cond_name}.template is required")

        # d) Reject unknown keys
        unknown = cond_raw.keys() - CONDITION_ALLOWED_KEYS
        if unknown:
            raise ConfigError(f"Unknown keys in conditions.{cond_name}: {unknown}")

        # e) Type check all values are str
        for key, val in cond_raw.items():
            if not isinstance(val, str):
                raise ConfigError(
                    f"conditions.{cond_name}.{key} must be str, got {type(val).__name__}"
                )

        # f) Validate template references exist in TEMPLATE_REGISTRY
        for key in ("template", "retry_template", "next_template"):
            tpl_name = cond_raw.get(key)
            if tpl_name is not None and tpl_name not in TEMPLATE_REGISTRY:
                raise ConfigError(
                    f"conditions.{cond_name}.{key} = '{tpl_name}' does not match "
                    f"any registered template. Known: {sorted(TEMPLATE_REGISTRY.keys())}"
                )

        # g) Structural invariants
        has_retry = "retry_template" in cond_raw
        has_next = "next_template" in cond_raw

        if cond_name in SIMPLE_CONDITIONS:
            if has_retry:
                raise ConfigError(
                    f"conditions.{cond_name} is a simple condition and "
                    f"MUST NOT have retry_template"
                )
            if has_next:
                raise ConfigError(
                    f"conditions.{cond_name} is a simple condition and "
                    f"MUST NOT have next_template"
                )
        elif cond_name in RETRY_CONDITIONS:
            if not has_retry:
                raise ConfigError(
                    f"conditions.{cond_name} is a retry condition and "
                    f"MUST have retry_template"
                )
            if has_next:
                raise ConfigError(
                    f"conditions.{cond_name} is a retry condition and "
                    f"MUST NOT have next_template"
                )
        elif cond_name in MULTISTEP_CONDITIONS:
            if not has_retry:
                raise ConfigError(
                    f"conditions.{cond_name} is a multistep condition and "
                    f"MUST have retry_template"
                )
            if not has_next:
                raise ConfigError(
                    f"conditions.{cond_name} is a multistep condition and "
                    f"MUST have next_template"
                )

        result[cond_name] = ConditionConfig(
            template=cond_raw["template"],
            retry_template=cond_raw.get("retry_template"),
            next_template=cond_raw.get("next_template"),
        )

    return result


# ============================================================
# LOAD + VALIDATE
# ============================================================

def load_config(path: Path) -> ExperimentConfig:
    """Load, validate, and freeze config. Raises on ANY error."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping at top level")

    return _validate_and_build(raw)


def _validate_and_build(raw: dict) -> ExperimentConfig:
    """Validate raw YAML dict and build frozen ExperimentConfig."""
    # 1. Top-level keys
    missing = REQUIRED_TOP_KEYS - raw.keys()
    if missing:
        raise ConfigError(f"Missing required top-level keys: {missing}")
    unknown = raw.keys() - REQUIRED_TOP_KEYS
    if unknown:
        raise ConfigError(f"Unknown top-level keys: {unknown}")

    # 2. Experiment section
    _validate_section(raw["experiment"], "experiment", EXPERIMENT_REQUIRED)
    exp = raw["experiment"]

    if exp["version"] != CURRENT_CONFIG_VERSION:
        raise ConfigError(
            f"experiment.version is {exp['version']}, expected {CURRENT_CONFIG_VERSION}. "
            f"This config file is not compatible with this version of the system."
        )

    models = exp["models"]
    if not models:
        raise ConfigError("experiment.models must be non-empty")
    for i, m in enumerate(models):
        if not isinstance(m, str):
            raise ConfigError(f"experiment.models[{i}] must be str, got {type(m).__name__}")

    # 3. Conditions section
    conditions = _validate_conditions(raw["conditions"])

    # 4. Retry section
    _validate_section(raw["retry"], "retry", RETRY_REQUIRED)
    retry_raw = raw["retry"]
    if retry_raw["strategy"] not in RETRY_STRATEGY_VALUES:
        raise ConfigError(
            f"retry.strategy must be one of {RETRY_STRATEGY_VALUES}, "
            f"got '{retry_raw['strategy']}'"
        )
    if not (1 <= retry_raw["max_steps"] <= 20):
        raise ConfigError("retry.max_steps must be in [1, 20]")

    # 5. Execution section
    _validate_section(raw["execution"], "execution", EXECUTION_REQUIRED)
    exec_raw = raw["execution"]
    if not (1 <= exec_raw["parallel"] <= 32):
        raise ConfigError("execution.parallel must be in [1, 32]")
    cases_path = BASE_DIR / exec_raw["cases_file"]
    if not cases_path.exists():
        raise ConfigError(
            f"execution.cases_file = '{exec_raw['cases_file']}' "
            f"does not exist at {cases_path}"
        )

    # 6. Logging section
    _validate_section(raw["logging"], "logging", LOGGING_REQUIRED)
    log_raw = raw["logging"]

    # 7. Freeze
    config = ExperimentConfig(
        version=exp["version"],
        name=exp["name"],
        models=tuple(models),
        conditions=conditions,
        retry=RetryConfig(
            enabled=retry_raw["enabled"],
            max_steps=retry_raw["max_steps"],
            strategy=retry_raw["strategy"],
        ),
        execution=ExecutionConfig(
            parallel=exec_raw["parallel"],
            cases_file=exec_raw["cases_file"],
            timeout_total_seconds=exec_raw["timeout_total_seconds"],
            timeout_per_step_seconds=exec_raw["timeout_per_step_seconds"],
        ),
        logging=LoggingConfig(
            run_dir_pattern=log_raw["run_dir_pattern"],
            log_resolved_config=log_raw["log_resolved_config"],
        ),
    )

    _log.info("Config loaded: %s (version=%d, %d conditions, %d models)",
              config.name, config.version, len(config.conditions), len(config.models))
    return config


# ============================================================
# UTILITIES
# ============================================================

def get_template_for_condition(config: ExperimentConfig, condition: str,
                                phase: str = "initial") -> str:
    """Get the template registry key for a condition and phase.

    Args:
        config: frozen experiment config
        condition: e.g., "retry_no_contract"
        phase: "initial", "retry", or "next"

    Returns:
        Template registry key (e.g., "base", "retry")
    """
    cond_cfg = config.conditions.get(condition)
    if cond_cfg is None:
        raise ConfigError(f"Condition '{condition}' not found in config.conditions")

    if phase == "initial":
        return cond_cfg.template
    elif phase == "retry":
        if cond_cfg.retry_template is None:
            raise ConfigError(
                f"Condition '{condition}' has no retry_template configured "
                f"but phase='retry' was requested"
            )
        return cond_cfg.retry_template
    elif phase == "next":
        if cond_cfg.next_template is None:
            raise ConfigError(
                f"Condition '{condition}' has no next_template configured "
                f"but phase='next' was requested"
            )
        return cond_cfg.next_template
    else:
        raise ConfigError(f"Unknown phase '{phase}'. Must be 'initial', 'retry', or 'next'.")


def _tuples_to_lists(obj):
    """Recursively convert tuples to lists for YAML serialization."""
    if isinstance(obj, tuple):
        return [_tuples_to_lists(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _tuples_to_lists(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_tuples_to_lists(item) for item in obj]
    return obj


def log_resolved_config(config: ExperimentConfig, run_dir: Path) -> Path:
    """Write config_resolved.yaml to run_dir. Returns path written."""
    d = _tuples_to_lists(dataclasses.asdict(config))
    out_path = run_dir / "config_resolved.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(d, f, default_flow_style=False)
    return out_path
