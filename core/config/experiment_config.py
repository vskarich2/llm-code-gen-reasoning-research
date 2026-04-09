"""Experiment configuration loader and validator.

The config is the SINGLE SOURCE OF TRUTH for all experimental parameters.
No hardcoded values in execution code. If a value is missing from config,
the system crashes with a clear error.

Usage:
    from core.config.experiment_config import load_config, get_config

    # At entry point (runner.py):
    config = load_config("config_storage/my_experiment.yaml")

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


def _require(d: dict, key: str, section: str):
    """Strict config extraction. Crashes on missing key."""
    if key not in d:
        raise ValueError(
            f"CONFIG ERROR: {section}.{key} is REQUIRED but missing from YAML. "
            f"All parameters must be explicitly defined in the config file."
        )
    return d[key]


def _require_section(d: dict, key: str) -> dict:
    """Require a YAML section exists and is a dict."""
    val = d.get(key)
    if val is None:
        raise ValueError(f"CONFIG ERROR: '{key}' section is REQUIRED but missing from YAML.")
    if not isinstance(val, dict):
        raise ValueError(f"CONFIG ERROR: '{key}' must be a YAML mapping, got {type(val).__name__}")
    return val

# ---------------------------------------------------------------------------
# Config dataclasses (typed, validated)
# ---------------------------------------------------------------------------


@dataclass
class ModelSpec:
    name: str
    temperature: float = 0.0
    max_tokens: int = 128000
    top_p: float = 1.0


@dataclass
class EvaluatorModelSpec:
    name: str
    temperature: float = 0.0
    max_tokens: int = 128000


@dataclass
class ModelsConfig:
    generation: list[ModelSpec]
    evaluator: EvaluatorModelSpec
    failure_classifier_name: str | None = None  # None = use evaluator
    no_temperature_prefixes: list[str] = field(default_factory=lambda: ["o1", "o3", "o4", "gpt-5"])

    @property
    def classifier_name(self) -> str:
        return self.failure_classifier_name or self.evaluator.name


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
    case_ids: list[str] = field(default_factory=list)  # optional explicit filter
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
    leg_enabled: bool = True
    failure_classification_enabled: bool = True
    alignment_enabled: bool = True
    classifier_mode: str = "blind"  # "blind" or "grounded"
    reasoning_correct_mode: str = "strict"  # "strict", "lenient", or "raw"
    classifier_template: str = "classify_reasoning_v2"  # .j2 template name for classifier
    classifier_schema_variant: str = "v2_semicolon"  # "v2_semicolon" | "v3_json"
    generation_schema_variant: str = "v2"  # "v2" | "v3"
    depth_hint_level: str | None = None  # "gentle", "directed", "explicit", or None (disabled)


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
class OracleConfig:
    inline_enabled: bool = True
    model: str = "gpt-5-mini"
    prompt_template: str = "reasoning_truth_prompt.j2"
    partial_mode: str = "lenient"         # "strict" | "lenient"
    sampling_strategy: str = "ALWAYS"     # "ALWAYS" | "FIRST_K(n)" | "RANDOM_SAMPLE(p)"
    # NOTE: per-call timeout is NOT supported. Timeout is controlled by the
    # API client (execution.anthropic_client_timeout). A per-call timeout
    # would require changes to call_model() and both provider wrappers.
    # Do not add a timeout field here — it would be a fake knob.


@dataclass
class ExecutionConfig:
    num_workers: int = 1
    worker_stagger_seconds: int = 3
    token_budgets: TokenBudgetConfig = field(default_factory=TokenBudgetConfig)
    import_summary: bool = False
    file_ordering: str = "dependency"
    output_format: str = "v2"
    mode: str = "canonical"  # "canonical" (disk-backed exec) or "legacy" (in-process exec)
    keep_eval_dirs: bool = False
    subprocess_timeout: int = 30
    worker_timeout_seconds: int = 600
    validate_prompts: bool = True  # run AST/metadata/structure checks on prompt templates at load
    worker_graceful_shutdown_seconds: int = 30
    recovery_execution: bool = True
    single_attempt_backend: str = "legacy_v2"  # "legacy_v2" | "graph_v1" | "shadow"
    retry_backend: str = "legacy_v2"  # "legacy_v2" | "graph_v1" | "shadow"
    max_orchestrator_attempts: int = 10
    anthropic_client_timeout: float = 120.0
    anthropic_max_output_tokens: int = 8192


@dataclass
class LoggingConfig:
    level: str = "INFO"
    output_dir: str = "logs/"
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_maxlen: int = 100_000


@dataclass
class RunConfig:
    """Per-run parameters. The config is the single source of truth.
    trial and run_id are optional when trials > 1 (orchestrator generates them)."""

    run_dir: str
    trial: int | None = None
    run_id: str | None = None


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
    oracle: OracleConfig = field(default_factory=OracleConfig)
    trials: int = 1

    # Runtime metadata (set by loader, not by YAML)
    _config_path: str = ""
    _config_sha256: str = ""
    _cli_overrides: dict = field(default_factory=dict)

    # Orchestrator identity (set by derive_trial_config, None in standalone)
    _work_id: str | None = None
    _instance_id: str | None = None
    _attempt: int | None = None
    _parent_config_sha256: str | None = None

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

    sha = hashlib.sha256(raw_text.encode()).hexdigest()

    # Apply CLI overrides before parsing
    if cli_overrides:
        _apply_overrides(raw, cli_overrides)

    config = _parse_config(raw)
    config._config_path = str(config_path.resolve())
    config._config_sha256 = sha
    config._cli_overrides = cli_overrides or {}

    # Orchestrator identity fields (present only in derived trial config_storage)
    config._work_id = raw.get("_work_id")
    config._instance_id = raw.get("_instance_id")
    config._attempt = raw.get("_attempt")
    config._parent_config_sha256 = raw.get("_parent_config_sha256")

    _validate(config)

    _config = config
    _log.info(
        "Config loaded: %s (sha=%s, %d models, %d conditions, cases=%s)",
        path,
        sha,
        len(config.models.generation),
        len(config.conditions),
        config.cases.source,
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
    generation = [
        ModelSpec(
            name=m["name"],
            temperature=m.get("temperature", 0.0),
            max_tokens=m.get("max_tokens", 128000),
            top_p=m.get("top_p", 1.0),
        )
        for m in gen_list
    ]

    eval_raw = models_raw.get("evaluator", {})
    if not eval_raw.get("name"):
        raise ValueError(
            "CONFIG ERROR: models.evaluator.name is REQUIRED. "
            "This was previously hardcoded and caused bugs. It must be explicit."
        )
    evaluator = EvaluatorModelSpec(
        name=eval_raw["name"],
        temperature=eval_raw.get("temperature", 0.0),
        max_tokens=eval_raw.get("max_tokens", 128000),
    )

    fc_raw = models_raw.get("failure_classifier", {})
    fc_name = fc_raw.get("name") if fc_raw else None

    models = ModelsConfig(
        generation=generation,
        evaluator=evaluator,
        failure_classifier_name=fc_name,
        no_temperature_prefixes=list(models_raw.get("no_temperature_prefixes", ["o1", "o3", "o4", "gpt-5"])),
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
        case_ids=cases_raw.get("case_ids", []),
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
        leg_enabled=eval_section.get("leg", {}).get("enabled", True),
        failure_classification_enabled=eval_section.get("failure_classification", {}).get(
            "enabled", True
        ),
        alignment_enabled=eval_section.get("alignment", {}).get("enabled", True),
        classifier_mode=eval_section.get("classifier_mode", "blind"),
        reasoning_correct_mode=eval_section.get("reasoning_correct_mode", "strict"),
        classifier_template=eval_section.get("classifier_template", "classify_reasoning_v2"),
        classifier_schema_variant=eval_section.get("classifier_schema_variant", "v2_semicolon"),
        generation_schema_variant=eval_section.get("generation_schema_variant", "v2"),
        depth_hint_level=eval_section.get("depth_hint_level", None),
    )

    _eval_allowed = {"leg", "failure_classification", "alignment",
                     "classifier_mode", "reasoning_correct_mode",
                     "classifier_template", "classifier_schema_variant",
                     "generation_schema_variant", "depth_hint_level"}
    _unknown_eval = set(eval_section.keys()) - _eval_allowed
    if _unknown_eval:
        raise ValueError(
            f"Unknown fields in evaluation config: {_unknown_eval}. "
            f"Valid fields: {sorted(_eval_allowed)}"
        )

    # Execution
    exec_raw = raw.get("execution", {})
    tb_raw = exec_raw.get("token_budgets", {})
    tb_default = tb_raw.pop("default", 10_000) if isinstance(tb_raw, dict) else 10_000
    token_budgets = TokenBudgetConfig(
        budgets=(
            {k: v for k, v in tb_raw.items() if k != "default"} if isinstance(tb_raw, dict) else {}
        ),
        default=tb_default,
    )
    v3_raw = exec_raw.get("v3_pipeline", {})
    # Unknown-key detection — derived from ExecutionConfig fields
    _exec_allowed = (
        set(ExecutionConfig.__dataclass_fields__.keys())
        - {"import_summary", "file_ordering", "output_format", "token_budgets"}
        | {"token_budgets", "v3_pipeline"}
    )
    _unknown_exec = set(exec_raw.keys()) - _exec_allowed
    if _unknown_exec:
        raise ValueError(
            f"Unknown fields in execution config: {_unknown_exec}. "
            f"Valid fields: {sorted(_exec_allowed)}"
        )

    execution = ExecutionConfig(
        num_workers=exec_raw.get("num_workers", 1),
        worker_stagger_seconds=exec_raw.get("worker_stagger_seconds", 3),
        token_budgets=token_budgets,
        import_summary=v3_raw.get("import_summary", False),
        file_ordering=v3_raw.get("file_ordering", "dependency"),
        output_format=raw.get("prompts", {}).get("output_format", "v2"),
        mode=exec_raw.get("mode", "canonical"),
        keep_eval_dirs=exec_raw.get("keep_eval_dirs", False),
        subprocess_timeout=exec_raw.get("subprocess_timeout", 30),
        worker_timeout_seconds=exec_raw.get("worker_timeout_seconds", 600),
        worker_graceful_shutdown_seconds=exec_raw.get("worker_graceful_shutdown_seconds", 30),
        validate_prompts=exec_raw.get("validate_prompts", True),
        recovery_execution=exec_raw.get("recovery_execution", True),
        max_orchestrator_attempts=exec_raw.get("max_orchestrator_attempts", 10),
        anthropic_client_timeout=exec_raw.get("anthropic_client_timeout", 120.0),
        anthropic_max_output_tokens=exec_raw.get("anthropic_max_output_tokens", 8192),
    )

    # Logging
    log_raw = raw.get("logging", {})
    redis_raw = log_raw.get("redis", {})
    logging_config = LoggingConfig(
        level=log_raw.get("level", "INFO"),
        output_dir=log_raw.get("output_dir", "logs/"),
        redis_enabled=redis_raw.get("enabled", False),
        redis_url=redis_raw.get("url", "redis://localhost:6379/0"),
        redis_stream_maxlen=redis_raw.get("stream_maxlen", 100_000),
    )

    _log_allowed = {"level", "output_dir", "redis"}
    _unknown_log = set(log_raw.keys()) - _log_allowed
    if _unknown_log:
        raise ValueError(
            f"Unknown fields in logging config: {_unknown_log}. "
            f"Valid fields: {sorted(_log_allowed)}"
        )

    # Oracle
    oracle_raw = raw.get("oracle", {})
    oracle = OracleConfig(
        inline_enabled=oracle_raw.get("inline_enabled", True),
        model=oracle_raw.get("model", "gpt-5-mini"),
        prompt_template=oracle_raw.get("prompt_template", "oracle_reasoning_truth"),
        partial_mode=oracle_raw.get("partial_mode", "lenient"),
        sampling_strategy=oracle_raw.get("sampling_strategy", "ALWAYS"),
    )
    if oracle.sampling_strategy.strip().upper() == "FINAL_ONLY":
        raise ValueError(
            "CONFIG ERROR: oracle.sampling_strategy='FINAL_ONLY' is not supported. "
            "FINAL_ONLY requires storing raw reasoning text in trajectory entries, "
            "which is not implemented. Use 'ALWAYS', 'FIRST_K(n)', or 'RANDOM_SAMPLE(p)'."
        )
    if "timeout" in oracle_raw:
        raise ValueError(
            "CONFIG ERROR: oracle.timeout is not supported. "
            "Per-call timeout cannot be plumbed through the current API wrapper chain. "
            "Timeout is controlled by execution.anthropic_client_timeout. "
            "Remove oracle.timeout from your config."
        )

    # Run
    run_raw = raw.get("run", {})
    if not run_raw:
        raise ValueError(
            "CONFIG ERROR: 'run' section is required. Must define at least run_dir. "
            "trial and run_id are optional when trials > 1 (orchestrator generates them)."
        )
    if "run_dir" not in run_raw or run_raw["run_dir"] is None:
        raise ValueError(
            "CONFIG ERROR: run.run_dir is required. "
            "The config is the single source of truth for run parameters."
        )
    run = RunConfig(
        run_dir=str(run_raw["run_dir"]),
        trial=int(run_raw["trial"]) if run_raw.get("trial") is not None else None,
        run_id=str(run_raw["run_id"]) if run_raw.get("run_id") is not None else None,
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
        oracle=oracle,
        trials=raw.get("trials", 1),
    )


def _parse_retry(raw: dict, defaults: RetryConfig | None = None) -> RetryConfig:
    """Parse retry config from YAML, filling from defaults where absent."""
    d = defaults or RetryConfig()
    return RetryConfig(
        enabled=raw.get("enabled", d.enabled),
        max_attempts=raw.get("max_attempts", d.max_attempts),
        include_test_output=raw.get("feedback", {}).get(
            "include_test_output", d.include_test_output
        ),
        include_critique=raw.get("feedback", {}).get("include_critique", d.include_critique),
        include_previous_code=raw.get("feedback", {}).get(
            "include_previous_code", d.include_previous_code
        ),
        stop_on_pass=raw.get("stopping", {}).get("stop_on_pass", d.stop_on_pass),
        stop_on_stagnation=raw.get("stopping", {}).get("stop_on_stagnation", d.stop_on_stagnation),
        stagnation_window=raw.get("stopping", {}).get("stagnation_window", d.stagnation_window),
        similarity_threshold=raw.get("similarity_threshold", d.similarity_threshold),
        score_epsilon=raw.get("score_epsilon", d.score_epsilon),
        persistence_escalation_count=raw.get(
            "persistence_escalation_count", d.persistence_escalation_count
        ),
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
            errors.append(
                f"models.generation[{m.name}].temperature: must be 0.0-2.0, got {m.temperature}"
            )
    if not config.models.evaluator.name:
        errors.append(
            "models.evaluator.name: REQUIRED (was previously hardcoded — must be explicit)"
        )

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

    # Run: trial and run_id required for single-trial mode
    if config.trials == 1:
        if config.run.trial is None:
            errors.append("run.trial: required when trials == 1")
        if config.run.run_id is None:
            errors.append("run.run_id: required when trials == 1")

    if errors:
        msg = "CONFIG VALIDATION FAILED:\n" + "\n".join(f"  [ERROR] {e}" for e in errors)
        raise ValueError(msg)

    _log.info("Config validation passed (%d checks OK)", 6 + len(config.conditions))


# ---------------------------------------------------------------------------
# Utility: dump config for reproducibility logging
# ---------------------------------------------------------------------------


def config_to_dict(config: ExperimentConfig) -> dict:
    """Serialize config to the canonical YAML schema.

    The parser expects:
      execution.v3_pipeline.import_summary
      execution.v3_pipeline.file_ordering
      prompts.output_format

    dataclasses.asdict() flattens these into execution.* — this
    function moves them back to the canonical locations.
    """
    import dataclasses

    def _to_dict(obj):
        if dataclasses.is_dataclass(obj):
            return {
                k: _to_dict(v) for k, v in dataclasses.asdict(obj).items() if not k.startswith("_")
            }
        elif isinstance(obj, (tuple, frozenset)):
            return [_to_dict(i) for i in obj]
        elif isinstance(obj, list):
            return [_to_dict(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: _to_dict(v) for k, v in obj.items()}
        return obj

    d = _to_dict(config)

    # Move fields from flat execution.* to canonical locations
    ex = d.get("execution", {})
    v3 = ex.pop("v3_pipeline", {})
    for field in ("import_summary", "file_ordering"):
        if field in ex:
            v3[field] = ex.pop(field)
    if v3:
        ex["v3_pipeline"] = v3

    output_format = ex.pop("output_format", None)
    if output_format is not None:
        d.setdefault("prompts", {})["output_format"] = output_format

    # Re-nest flat evaluation fields to match YAML schema
    ev = d.get("evaluation", {})
    for flat_key, nested_key in [
        ("leg_enabled", "leg"),
        ("failure_classification_enabled", "failure_classification"),
        ("alignment_enabled", "alignment"),
    ]:
        if flat_key in ev:
            ev[nested_key] = {"enabled": ev.pop(flat_key)}

    # Re-nest flat logging fields to match YAML schema
    lg = d.get("logging", {})
    redis_section = {}
    for flat_key, nested_key in [
        ("redis_enabled", "enabled"),
        ("redis_url", "url"),
        ("redis_stream_maxlen", "stream_maxlen"),
    ]:
        if flat_key in lg:
            redis_section[nested_key] = lg.pop(flat_key)
    if redis_section:
        lg["redis"] = redis_section

    d["_config_path"] = config._config_path
    d["_config_sha256"] = config._config_sha256
    d["_cli_overrides"] = config._cli_overrides
    return d
