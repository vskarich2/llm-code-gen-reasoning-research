"""Experiment configuration loader and validator.

The config is the SINGLE SOURCE OF TRUTH for all experimental parameters.
No hardcoded values in execution code. If a value is missing from config,
the system crashes with a clear error.

Usage:
    from experiment_config import load_config, get_config

    # At entry point (runner.py):
    config = load_config("configs/my_experiment.yaml")

    # Anywhere else (after load_config has been called):
    config = get_config()
    model = config.models.evaluator.name
"""

import copy
import hashlib
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_log = logging.getLogger("t3.config")

# ---------------------------------------------------------------------------
# Config dataclasses (typed, validated)
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    name: str
    temperature: float = 0.0
    max_tokens: int = 4096
    top_p: float = 1.0


@dataclass
class EvaluatorModelSpec:
    name: str
    temperature: float = 0.0
    max_tokens: int = 1024
    max_task_chars: int = 800
    max_code_chars: int = 2000
    max_reasoning_chars: int = 1000


@dataclass
class ModelsConfig:
    generation: list[ModelSpec]
    evaluator: EvaluatorModelSpec
    failure_classifier_name: str | None = None  # None = use evaluator

    @property
    def classifier_name(self) -> str:
        return self.failure_classifier_name or self.evaluator.name

    @property
    def no_temperature_prefixes(self) -> tuple[str, ...]:
        return ("o1", "o3", "o4", "gpt-5")


@dataclass
class RetryConfig:
    enabled: bool = False
    max_attempts: int = 5
    include_test_output: bool = True
    include_critique: bool = False
    include_previous_code: bool = True
    stop_on_pass: bool = True
    stop_on_stagnation: bool = False
    stagnation_window: int = 3
    similarity_threshold: float = 0.95
    score_epsilon: float = 0.05
    persistence_escalation_count: int = 2
    max_iteration_seconds: int = 60
    max_total_seconds: int = 360


@dataclass
class ConditionConfig:
    prompt_template: str
    retry: RetryConfig = field(default_factory=RetryConfig)
    contract_enabled: bool = False
    contract_injection_point: str = "before_code"
    critique_enabled: bool = False
    critique_model: str | None = None


@dataclass
class CasesConfig:
    source: str
    mode: str = "all"
    subset: list[str] = field(default_factory=list)
    max_cases: int = 0
    # Filters
    difficulty_filter: list[str] = field(default_factory=list)
    family_filter: list[str] = field(default_factory=list)
    min_files: int = 1
    exclude: list[str] = field(default_factory=list)


@dataclass
class EvaluationConfig:
    execution_mode: str = "subprocess"
    subprocess_timeout: int = 30
    leg_enabled: bool = True
    failure_classification_enabled: bool = True
    alignment_enabled: bool = True


@dataclass
class TokenBudgetConfig:
    budgets: dict[str, int] = field(default_factory=dict)
    default: int = 10_000

    def get_budget(self, model: str) -> int:
        for prefix, budget in self.budgets.items():
            if model.startswith(prefix):
                return budget
        return self.default


@dataclass
class ExecutionConfig:
    num_workers: int = 1
    token_budgets: TokenBudgetConfig = field(default_factory=TokenBudgetConfig)
    import_summary: bool = False
    file_ordering: str = "dependency"
    output_format: str = "v2"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    output_dir: str = "logs/"
    store_raw_prompts: bool = True
    store_raw_outputs: bool = True
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_maxlen: int = 100_000


@dataclass
class RunConfig:
    """Per-run parameters. The config is the single source of truth."""
    trial: int
    run_id: str
    run_dir: str


@dataclass
class ExperimentMetadata:
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    seed: int | None = None


@dataclass
class ExperimentConfig:
    """Top-level experiment configuration. The single source of truth."""
    experiment: ExperimentMetadata
    models: ModelsConfig
    conditions: dict[str, ConditionConfig]
    cases: CasesConfig
    run: RunConfig
    retry_defaults: RetryConfig
    evaluation: EvaluationConfig
    execution: ExecutionConfig
    logging: LoggingConfig
    trials: int = 1

    # Runtime metadata (set by loader, not by YAML)
    _config_path: str = ""
    _config_sha256: str = ""
    _cli_overrides: dict = field(default_factory=dict)

    def get_generation_model(self, name: str) -> ModelSpec:
        for m in self.models.generation:
            if m.name == name:
                return m
        raise ValueError(
            f"CONFIG ERROR: generation model '{name}' not found in config. "
            f"Available: {[m.name for m in self.models.generation]}"
        )


# ---------------------------------------------------------------------------
# Global config singleton
# ---------------------------------------------------------------------------

_config: ExperimentConfig | None = None


def get_config() -> ExperimentConfig:
    """Return the loaded config. Crashes if not loaded."""
    if _config is None:
        raise RuntimeError(
            "CONFIG NOT LOADED. Call load_config() at the entry point before "
            "any pipeline code runs. The config is the single source of truth — "
            "the system cannot operate without it."
        )
    return _config


def is_config_loaded() -> bool:
    return _config is not None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(path: str, cli_overrides: dict | None = None) -> ExperimentConfig:
    """Load, validate, and activate a config file.

    This is called exactly once at the entry point (runner.py).
    After this call, get_config() returns the loaded config from anywhere.
    """
    global _config

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw_text = config_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must be a YAML mapping, got {type(raw).__name__}")

    sha = hashlib.sha256(raw_text.encode()).hexdigest()[:16]

    # Apply CLI overrides before parsing
    if cli_overrides:
        _apply_overrides(raw, cli_overrides)

    config = _parse_config(raw)
    config._config_path = str(config_path.resolve())
    config._config_sha256 = sha
    config._cli_overrides = cli_overrides or {}

    _validate(config)

    _config = config
    _log.info(
        "Config loaded: %s (sha=%s, %d models, %d conditions, cases=%s)",
        path, sha, len(config.models.generation),
        len(config.conditions), config.cases.source,
    )
    return config


def _apply_overrides(raw: dict, overrides: dict) -> None:
    """Apply dotted-path overrides to raw YAML dict."""
    for key, value in overrides.items():
        parts = key.split(".")
        target = raw
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value


def _parse_config(raw: dict) -> ExperimentConfig:
    """Parse raw YAML dict into typed ExperimentConfig."""
    # Experiment metadata
    exp_raw = raw.get("experiment", {})
    if not exp_raw.get("name"):
        raise ValueError("CONFIG ERROR: experiment.name is required")
    experiment = ExperimentMetadata(
        name=exp_raw["name"],
        description=exp_raw.get("description", ""),
        tags=exp_raw.get("tags", []),
        seed=exp_raw.get("seed"),
    )

    # Models
    models_raw = raw.get("models", {})
    gen_list = models_raw.get("generation", [])
    if not gen_list:
        raise ValueError("CONFIG ERROR: models.generation must have at least one model")
    generation = [ModelSpec(
        name=m["name"],
        temperature=m.get("temperature", 0.0),
        max_tokens=m.get("max_tokens", 4096),
        top_p=m.get("top_p", 1.0),
    ) for m in gen_list]

    eval_raw = models_raw.get("evaluator", {})
    if not eval_raw.get("name"):
        raise ValueError(
            "CONFIG ERROR: models.evaluator.name is REQUIRED. "
            "This was previously hardcoded and caused bugs. It must be explicit."
        )
    evaluator = EvaluatorModelSpec(
        name=eval_raw["name"],
        temperature=eval_raw.get("temperature", 0.0),
        max_tokens=eval_raw.get("max_tokens", 1024),
        max_task_chars=eval_raw.get("max_task_chars", 800),
        max_code_chars=eval_raw.get("max_code_chars", 2000),
        max_reasoning_chars=eval_raw.get("max_reasoning_chars", 1000),
    )

    fc_raw = models_raw.get("failure_classifier", {})
    fc_name = fc_raw.get("name") if fc_raw else None

    models = ModelsConfig(
        generation=generation,
        evaluator=evaluator,
        failure_classifier_name=fc_name,
    )

    # Retry defaults
    rd_raw = raw.get("retry_defaults", {})
    retry_defaults = _parse_retry(rd_raw)

    # Conditions
    cond_raw = raw.get("conditions", {})
    if not cond_raw:
        raise ValueError("CONFIG ERROR: conditions must define at least one condition")
    conditions = {}
    for cname, cdef in cond_raw.items():
        retry_section = cdef.get("retry", {})
        retry = _parse_retry(retry_section, defaults=retry_defaults)
        conditions[cname] = ConditionConfig(
            prompt_template=cdef.get("prompt_template", cname),
            retry=retry,
            contract_enabled=cdef.get("contract", {}).get("enabled", False),
            contract_injection_point=cdef.get("contract", {}).get("injection_point", "before_code"),
            critique_enabled=cdef.get("critique", {}).get("enabled", False),
            critique_model=cdef.get("critique", {}).get("critique_model"),
        )

    # Cases
    cases_raw = raw.get("cases", {})
    if not cases_raw.get("source"):
        raise ValueError("CONFIG ERROR: cases.source is required")
    cases = CasesConfig(
        source=cases_raw["source"],
        mode=cases_raw.get("mode", "all"),
        subset=cases_raw.get("subset", []),
        max_cases=cases_raw.get("max_cases", 0),
        difficulty_filter=cases_raw.get("filters", {}).get("difficulty", []),
        family_filter=cases_raw.get("filters", {}).get("family", []),
        min_files=cases_raw.get("filters", {}).get("min_files", 1),
        exclude=cases_raw.get("filters", {}).get("exclude", []),
    )

    # Evaluation
    eval_section = raw.get("evaluation", {})
    evaluation = EvaluationConfig(
        execution_mode=eval_section.get("execution_mode", "subprocess"),
        subprocess_timeout=eval_section.get("subprocess_timeout", 30),
        leg_enabled=eval_section.get("leg", {}).get("enabled", True),
        failure_classification_enabled=eval_section.get("failure_classification", {}).get("enabled", True),
        alignment_enabled=eval_section.get("alignment", {}).get("enabled", True),
    )

    # Execution
    exec_raw = raw.get("execution", {})
    tb_raw = exec_raw.get("token_budgets", {})
    tb_default = tb_raw.pop("default", 10_000) if isinstance(tb_raw, dict) else 10_000
    token_budgets = TokenBudgetConfig(
        budgets={k: v for k, v in tb_raw.items() if k != "default"} if isinstance(tb_raw, dict) else {},
        default=tb_default,
    )
    v3_raw = exec_raw.get("v3_pipeline", {})
    execution = ExecutionConfig(
        num_workers=exec_raw.get("num_workers", 1),
        token_budgets=token_budgets,
        import_summary=v3_raw.get("import_summary", False),
        file_ordering=v3_raw.get("file_ordering", "dependency"),
        output_format=raw.get("prompts", {}).get("output_format", "v2"),
    )

    # Logging
    log_raw = raw.get("logging", {})
    redis_raw = log_raw.get("redis", {})
    logging_config = LoggingConfig(
        level=log_raw.get("level", "INFO"),
        output_dir=log_raw.get("output_dir", "logs/"),
        store_raw_prompts=log_raw.get("store", {}).get("raw_prompts", True),
        store_raw_outputs=log_raw.get("store", {}).get("raw_outputs", True),
        redis_enabled=redis_raw.get("enabled", False),
        redis_url=redis_raw.get("url", "redis://localhost:6379/0"),
        redis_stream_maxlen=redis_raw.get("stream_maxlen", 100_000),
    )

    # Run
    run_raw = raw.get("run", {})
    if not run_raw:
        raise ValueError(
            "CONFIG ERROR: 'run' section is required. Must define trial, run_id, run_dir. "
            "These cannot be set via CLI — the config is the single source of truth."
        )
    for req_field in ("trial", "run_id", "run_dir"):
        if req_field not in run_raw or run_raw[req_field] is None:
            raise ValueError(
                f"CONFIG ERROR: run.{req_field} is required. "
                f"The config is the single source of truth for run parameters."
            )
    run = RunConfig(
        trial=int(run_raw["trial"]),
        run_id=str(run_raw["run_id"]),
        run_dir=str(run_raw["run_dir"]),
    )

    return ExperimentConfig(
        experiment=experiment,
        models=models,
        conditions=conditions,
        cases=cases,
        run=run,
        retry_defaults=retry_defaults,
        evaluation=evaluation,
        execution=execution,
        logging=logging_config,
        trials=raw.get("trials", 1),
    )


def _parse_retry(raw: dict, defaults: RetryConfig | None = None) -> RetryConfig:
    """Parse retry config from YAML, filling from defaults where absent."""
    d = defaults or RetryConfig()
    return RetryConfig(
        enabled=raw.get("enabled", d.enabled),
        max_attempts=raw.get("max_attempts", d.max_attempts),
        include_test_output=raw.get("feedback", {}).get("include_test_output", d.include_test_output),
        include_critique=raw.get("feedback", {}).get("include_critique", d.include_critique),
        include_previous_code=raw.get("feedback", {}).get("include_previous_code", d.include_previous_code),
        stop_on_pass=raw.get("stopping", {}).get("stop_on_pass", d.stop_on_pass),
        stop_on_stagnation=raw.get("stopping", {}).get("stop_on_stagnation", d.stop_on_stagnation),
        stagnation_window=raw.get("stopping", {}).get("stagnation_window", d.stagnation_window),
        similarity_threshold=raw.get("similarity_threshold", d.similarity_threshold),
        score_epsilon=raw.get("score_epsilon", d.score_epsilon),
        persistence_escalation_count=raw.get("persistence_escalation_count", d.persistence_escalation_count),
        max_iteration_seconds=raw.get("max_iteration_seconds", d.max_iteration_seconds),
        max_total_seconds=raw.get("max_total_seconds", d.max_total_seconds),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(config: ExperimentConfig) -> None:
    """Validate config. Raises on any error. Errors are fatal."""
    errors = []

    # Models
    if not config.models.generation:
        errors.append("models.generation: must have at least one model")
    for m in config.models.generation:
        if not m.name:
            errors.append("models.generation[].name: must be non-empty")
        if not (0.0 <= m.temperature <= 2.0):
            errors.append(f"models.generation[{m.name}].temperature: must be 0.0-2.0, got {m.temperature}")
    if not config.models.evaluator.name:
        errors.append("models.evaluator.name: REQUIRED (was previously hardcoded — must be explicit)")

    # Conditions
    if not config.conditions:
        errors.append("conditions: must define at least one condition")
    for cname, cond in config.conditions.items():
        if cond.critique_enabled and not cond.retry.enabled:
            errors.append(f"conditions.{cname}: critique requires retry to be enabled")

    # Cases
    if not config.cases.source:
        errors.append("cases.source: required")

    # Trials
    if config.trials < 1:
        errors.append(f"trials: must be >= 1, got {config.trials}")

    if errors:
        msg = "CONFIG VALIDATION FAILED:\n" + "\n".join(f"  [ERROR] {e}" for e in errors)
        raise ValueError(msg)

    _log.info("Config validation passed (%d checks OK)", 6 + len(config.conditions))


# ---------------------------------------------------------------------------
# Utility: dump config for reproducibility logging
# ---------------------------------------------------------------------------

def config_to_dict(config: ExperimentConfig) -> dict:
    """Serialize config to a plain dict for JSON logging."""
    import dataclasses
    def _to_dict(obj):
        if dataclasses.is_dataclass(obj):
            return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()
                    if not k.startswith("_")}
        elif isinstance(obj, list):
            return [_to_dict(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        return obj
    d = _to_dict(config)
    d["_config_path"] = config._config_path
    d["_config_sha256"] = config._config_sha256
    d["_cli_overrides"] = config._cli_overrides
    return d
