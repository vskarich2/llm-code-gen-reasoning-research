# DESIGN PLAN: Retry + Trajectory, Config System, Templating System

**Version:** v3
**Date:** 2026-03-24
**Status:** Design complete, pending implementation
**Depends on:** retry_harness.py (implemented), runner.py, execution.py, evaluator.py, prompts.py
**Supersedes:** CONFIG_TEMPLATE_RETRY_SYSTEM_PLAN_v2.md

---

## CHANGELOG (v2 -> v3)

| Fix | What Changed | Rationale |
|---|---|---|
| FIX 1 | Added condition-category structural invariants: `RETRY_CONDITIONS`, `MULTISTEP_CONDITIONS`, `SIMPLE_CONDITIONS` enforced during config validation | Prevents invalid states like baseline having retry_template. |
| FIX 2 | Template hashes computed ONCE at startup into a frozen dict. No lazy cache, no recompute. | Eliminates stale hash risk entirely. |
| FIX 3 | Hash computed via `env.loader.get_source()` instead of raw file read | Guarantees hash matches the exact source Jinja2 compiles and renders. |
| FIX 4 | Added `experiment.version: 1` with strict version check on load | Forward-compatible config versioning. Unknown versions rejected. |
| FIX 5 | `run_retry_harness()` receives `condition: str` as an explicit parameter. All flag-based inference removed. | No implicit logic. Caller (runner) passes the condition it already knows. |
| FIX 6 | Template logic rule relaxed: `{% if %}` / `{% endif %}` allowed. Loops, macros, and complex logic still forbidden. | Conditional blocks are needed for optional template sections while keeping templates simple. |

### Full changelog (v1 -> v2, retained)

| Fix | What Changed | Rationale |
|---|---|---|
| v2 FIX 1 | Removed `prompt_vars` section from config and `PromptVarsConfig` dataclass | Template variable requirements exist ONLY in `TemplateSpec.required_vars`. One source of truth. |
| v2 FIX 2 | Moved condition-to-template mapping from hardcoded `CONDITION_TEMPLATE_MAP` into config YAML | No hidden logic. Config is the single authority for which template each condition uses. |
| v2 FIX 3 | Removed "template must contain placeholder string" check from preflight dry-render | Over-strict and brittle. StrictUndefined + pre-render var set check are sufficient. |
| v2 FIX 4 | Added template versioning: SHA-256 hash of each template, logged with every rendered prompt | Required for reproducibility -- detects template file changes between runs. |
| v2 FIX 5 | Removed `from runner import VALID_CONDITIONS`. Created `constants.py` as shared source of truth | Config must not depend on runtime code. |
| v2 FIX 6 | Added full variable dictionary to prompt log record | Full variable capture enables complete prompt reconstruction from logs. |

---

## 1. SYSTEM ARCHITECTURE OVERVIEW

### Current State

The system currently has:
- **31 experimental conditions** dispatched via `runner.py` -> `execution.py:build_prompt()` -> condition-specific branches
- **Prompts built as raw Python f-strings** in `prompts.py`, `contract.py`, `scm_prompts.py`, `reasoning_prompts.py`, `nudges/operators.py`
- **A retry harness** (`retry_harness.py`) with 5-iteration loops, failure classification, trajectory analysis -- but no step/retry metadata in events
- **Minimal config** (`ablation_config.yaml`) -- 21 lines, read by shell scripts but NOT loaded or validated by Python code
- **No Jinja2** anywhere -- all prompt construction is string concatenation

### Target State

Three new subsystems integrated into the existing pipeline:

```
                    +------------------+
                    |  experiment.yaml |  (PART 2: Config)
                    |  STRICT SCHEMA   |
                    +--------+---------+
                             | load + validate + freeze
                             v
                    +------------------+
                    | ExperimentConfig |  (frozen dataclass)
                    +--------+---------+
                             |
              +--------------+--------------+
              v              v              v
    +--------------+  +---------------+  +--------------+
    | Template     |  | Retry         |  | Runner       |
    | Registry     |  | Engine        |  | (existing)   |
    | (PART 3)     |  | (PART 1)      |  |              |
    +------+-------+  +------+--------+  +--------------+
           |                 |
           v                 v
    +--------------+  +---------------+
    | Jinja2       |  | Trajectory    |
    | StrictUndef  |  | Events        |
    +--------------+  +---------------+
```

### New Files

| File | Purpose |
|---|---|
| `constants.py` | Shared constants: `VALID_CONDITIONS`, condition labels, condition categories |
| `config.py` | Config loader, validator, frozen dataclass |
| `templates.py` | Template registry, Jinja2 renderer, validation, hashing |
| `templates/base.jinja2` | Base prompt template |
| `templates/retry.jinja2` | Retry prompt template |
| `templates/contract_elicit.jinja2` | Contract elicitation template |
| `templates/contract_code.jinja2` | Contract-conditioned code gen template |
| `templates/contract_retry.jinja2` | Contract retry template |
| `templates/repair_feedback.jinja2` | Repair loop feedback template |
| `templates/classify.jinja2` | LLM classifier template |
| `tests/test_config.py` | Config system tests |
| `tests/test_templates.py` | Template system tests |
| `tests/test_retry_trajectory.py` | Retry trajectory event tests |
| `tests/test_integration_config_template.py` | Integration tests |

### Modified Files

| File | Change |
|---|---|
| `runner.py` | Import conditions from `constants.py`; load config at startup; pass condition explicitly to retry harness |
| `retry_harness.py` | Accept `condition` as explicit parameter; add `step`, `is_retry`, `retry_reason`, `prev_failure_type` to events |
| `execution.py` | Route through template renderer; emit extended events |
| `live_metrics.py` | Accept extended event fields |
| `ablation_config.yaml` -> `experiment.yaml` | Replaced with strict schema |

---

## 2. SHARED CONSTANTS MODULE

### 2.1 Purpose

Config validation, runner dispatch, and structural invariant enforcement all need the set of valid conditions and their categories. All import from `constants.py`, which imports nothing from the project.

### 2.2 File: `constants.py`

```python
"""Shared constants for T3 benchmark.

This module is the SOLE source of truth for condition names, labels, and categories.
Imported by: config.py, runner.py, execution.py.
Must NOT import from any of those modules (no circular deps).
"""

ALL_CONDITIONS = [
    "baseline", "diagnostic", "guardrail",
    "guardrail_strict", "counterfactual", "reason_then_act",
    "self_check", "counterfactual_check", "test_driven",
    "repair_loop",
    # SCM experiment conditions
    "scm_descriptive", "scm_constrained", "scm_constrained_evidence",
    "scm_constrained_evidence_minimal", "evidence_only", "length_matched_control",
    # Reasoning interface conditions
    "structured_reasoning", "free_form_reasoning", "branching_reasoning",
    # Contract-Gated Execution
    "contract_gated",
    # Retry harness (trajectory probe)
    "retry_no_contract", "retry_with_contract", "retry_adaptive",
    "retry_alignment",
    # LEG-reduction (intra-call self-correction)
    "leg_reduction",
]

VALID_CONDITIONS = frozenset(ALL_CONDITIONS)

# ── Condition categories (structural invariants for config validation) ──
#
# These define which template keys are REQUIRED and FORBIDDEN per condition.

# Conditions that use a retry loop with retry_template. MUST have retry_template. MUST NOT have next_template.
RETRY_CONDITIONS = frozenset({
    "retry_no_contract", "retry_with_contract", "retry_adaptive", "retry_alignment",
    "repair_loop",
})

# Multi-step conditions. MUST have BOTH next_template and retry_template.
MULTISTEP_CONDITIONS = frozenset({
    "contract_gated",
})

# All other conditions. MUST have ONLY template. MUST NOT have retry_template or next_template.
SIMPLE_CONDITIONS = VALID_CONDITIONS - RETRY_CONDITIONS - MULTISTEP_CONDITIONS

# INVARIANT: categories must be exhaustive and non-overlapping
assert RETRY_CONDITIONS | MULTISTEP_CONDITIONS | SIMPLE_CONDITIONS == VALID_CONDITIONS
assert not (RETRY_CONDITIONS & MULTISTEP_CONDITIONS)
assert not (RETRY_CONDITIONS & SIMPLE_CONDITIONS)
assert not (MULTISTEP_CONDITIONS & SIMPLE_CONDITIONS)

COND_LABELS = {
    "baseline": "BL", "diagnostic": "DX", "guardrail": "GR",
    "guardrail_strict": "GS", "counterfactual": "CF", "reason_then_act": "RA",
    "self_check": "SC", "counterfactual_check": "CC", "test_driven": "TD",
    "repair_loop": "RL",
    "scm_descriptive": "SD", "scm_constrained": "SK", "scm_constrained_evidence": "SE",
    "scm_constrained_evidence_minimal": "SM", "evidence_only": "EO", "length_matched_control": "LC",
    "structured_reasoning": "SR", "free_form_reasoning": "FF", "branching_reasoning": "BR",
    "contract_gated": "CG",
    "retry_no_contract": "RN", "retry_with_contract": "RC", "retry_adaptive": "AD",
    "retry_alignment": "AL",
    "leg_reduction": "LR",
}

# INVARIANT: condition labels must be unique
assert len(set(COND_LABELS.values())) == len(COND_LABELS), (
    f"FATAL: Duplicate condition labels detected."
)

# INVARIANT: every condition must have a label
assert set(COND_LABELS.keys()) == VALID_CONDITIONS, (
    f"FATAL: COND_LABELS keys do not match VALID_CONDITIONS."
)

# Current config schema version
CURRENT_CONFIG_VERSION = 1
```

### 2.3 Migration

`runner.py` deletes its local `ALL_CONDITIONS`, `VALID_CONDITIONS`, `COND_LABELS` and replaces with:
```python
from constants import ALL_CONDITIONS, VALID_CONDITIONS, COND_LABELS
```

`config.py` imports:
```python
from constants import (
    VALID_CONDITIONS, RETRY_CONDITIONS, MULTISTEP_CONDITIONS, SIMPLE_CONDITIONS,
    CURRENT_CONFIG_VERSION,
)
```

No circular dependency. `constants.py` imports nothing from the project.

---

## 3. CONFIG SYSTEM (PART 2)

### 3.1 Schema Definition

File: `experiment.yaml`

```yaml
experiment:
  version: 1                          # int, required, must equal CURRENT_CONFIG_VERSION
  name: "retry_ablation_v2"          # str, required
  models:                             # list[str], required, min 1
    - "gpt-4o-mini"
    - "gpt-5-mini"

conditions:                           # dict[str, ConditionConfig], required, min 1 entry
  baseline:
    template: "base"
  diagnostic:
    template: "base"
  guardrail:
    template: "base"
  guardrail_strict:
    template: "base"
  counterfactual:
    template: "base"
  reason_then_act:
    template: "base"
  self_check:
    template: "base"
  counterfactual_check:
    template: "base"
  test_driven:
    template: "base"
  repair_loop:
    template: "base"
    retry_template: "repair_feedback"
  contract_gated:
    template: "contract_elicit"
    next_template: "contract_code"
    retry_template: "contract_retry"
  retry_no_contract:
    template: "base"
    retry_template: "retry"
  retry_with_contract:
    template: "base"
    retry_template: "retry"
  retry_adaptive:
    template: "base"
    retry_template: "retry"
  retry_alignment:
    template: "base"
    retry_template: "retry"
  leg_reduction:
    template: "base"

retry:
  enabled: true                       # bool, required
  max_steps: 5                        # int, required, range [1, 20]
  strategy: "linear"                  # str, required, one of: "linear"

execution:
  parallel: 1                         # int, required, range [1, 32]
  cases_file: "cases_v2.json"         # str, required, must exist on disk
  timeout_total_seconds: 360          # int, required
  timeout_per_step_seconds: 60        # int, required

logging:
  run_dir_pattern: "ablation_runs/run_{model}_t{trial}_{uuid}"  # str, required
  log_resolved_config: true           # bool, required
```

### 3.2 Python Schema (Frozen Dataclasses)

File: `config.py`

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ConditionConfig:
    """Config for a single experimental condition."""
    template: str                        # registry key for initial prompt
    retry_template: str | None = None    # registry key for retry/feedback prompt
    next_template: str | None = None     # registry key for multi-step next prompt

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
    conditions: dict[str, ConditionConfig]   # condition_name -> ConditionConfig
    retry: RetryConfig
    execution: ExecutionConfig
    logging: LoggingConfig
```

### 3.3 Loader and Validator

```python
def load_config(path: Path) -> ExperimentConfig:
    """Load, validate, and freeze config. Raises on ANY error."""
```

**Validation steps (in order, all mandatory):**

1. **File exists**: `if not path.exists(): raise FileNotFoundError(...)`

2. **YAML parse**: `yaml.safe_load()` -- raises on invalid YAML

3. **Top-level keys check**:
   ```python
   REQUIRED_TOP_KEYS = {"experiment", "conditions", "retry", "execution", "logging"}
   missing = REQUIRED_TOP_KEYS - raw.keys()
   if missing:
       raise ConfigError(f"Missing required top-level keys: {missing}")
   unknown = raw.keys() - REQUIRED_TOP_KEYS
   if unknown:
       raise ConfigError(f"Unknown top-level keys: {unknown}")
   ```

4. **Experiment section validation (including version check -- FIX 4)**:
   ```python
   EXPERIMENT_REQUIRED = {"version": int, "name": str, "models": list}

   exp = raw["experiment"]
   # ... standard type/key checks ...

   # VERSION CHECK (FIX 4)
   if exp["version"] != CURRENT_CONFIG_VERSION:
       raise ConfigError(
           f"experiment.version is {exp['version']}, expected {CURRENT_CONFIG_VERSION}. "
           f"This config file is not compatible with this version of the system."
       )
   ```

5. **Conditions section validation (with structural invariants -- FIX 1)**:
   ```python
   CONDITION_ALLOWED_KEYS = {"template", "retry_template", "next_template"}

   conditions_raw = raw["conditions"]
   if not isinstance(conditions_raw, dict) or len(conditions_raw) == 0:
       raise ConfigError("conditions must be a non-empty dict")

   for cond_name, cond_raw in conditions_raw.items():
       # a) Validate condition name against shared constants
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

       # f) Validate all template references exist in TEMPLATE_REGISTRY
       from templates import TEMPLATE_REGISTRY
       for key in ("template", "retry_template", "next_template"):
           tpl_name = cond_raw.get(key)
           if tpl_name is not None and tpl_name not in TEMPLATE_REGISTRY:
               raise ConfigError(
                   f"conditions.{cond_name}.{key} = '{tpl_name}' does not match "
                   f"any registered template. Known: {sorted(TEMPLATE_REGISTRY.keys())}"
               )

       # g) STRUCTURAL INVARIANTS (FIX 1)
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
   ```

6. **Retry section validation**:
   ```python
   RETRY_REQUIRED = {"enabled": bool, "max_steps": int, "strategy": str}
   RETRY_STRATEGY_VALUES = {"linear"}
   # validate types, reject unknown keys, validate range [1, 20], validate enum
   ```

7. **Execution section validation**:
   ```python
   EXECUTION_REQUIRED = {
       "parallel": int, "cases_file": str,
       "timeout_total_seconds": int, "timeout_per_step_seconds": int,
   }
   # validate types, reject unknown keys, validate parallel in [1, 32]
   # validate cases_file exists on disk
   ```

8. **Logging section validation**:
   ```python
   LOGGING_REQUIRED = {"run_dir_pattern": str, "log_resolved_config": bool}
   # validate types, reject unknown keys
   ```

9. **Freeze**: Construct frozen dataclasses. Convert lists to tuples. Convert conditions dict entries to `ConditionConfig` objects.

### 3.4 How Runner Reads the Condition-Template Mapping

```python
def get_template_for_condition(config: ExperimentConfig, condition: str,
                                phase: str = "initial") -> str:
    """Get the template registry key for a condition and phase.

    Args:
        config: frozen experiment config
        condition: e.g., "retry_no_contract"
        phase: "initial", "retry", or "next"

    Returns:
        Template registry key (e.g., "base", "retry")

    Raises:
        ConfigError: if condition not in config or requested phase has no template
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
```

### 3.5 Config Logging

```python
def log_resolved_config(config: ExperimentConfig, run_dir: Path) -> Path:
    """Write config_resolved.yaml to run_dir. Returns path written."""
    import dataclasses, yaml
    d = dataclasses.asdict(config)
    out_path = run_dir / "config_resolved.yaml"
    with open(out_path, "w") as f:
        yaml.dump(d, f, default_flow_style=False)
    return out_path
```

**Invariant**: `config_resolved.yaml` in every run directory is the EXACT config that produced that run's data.

### 3.6 Integration Point

In `runner.py:main()` and `runner.py:_run_ablation_mode()`:

```python
config = load_config(BASE_DIR / args.config)  # new --config arg, default "experiment.yaml"
# All downstream code receives `config`, never reads raw YAML again
```

The config object is passed explicitly -- never stored in module-level globals.

---

## 4. TEMPLATE SYSTEM (PART 3)

### 4.1 Template Registry

File: `templates.py`

```python
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

_tpl_log = logging.getLogger("t3.templates")
BASE_DIR = Path(__file__).parent

@dataclass(frozen=True)
class TemplateSpec:
    name: str
    path: str                        # relative to project root (e.g., "templates/base.jinja2")
    required_vars: frozenset[str]    # SOLE source of truth for variable requirements

# Central registry -- every template the system uses MUST be registered here.
TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {}

def register(spec: TemplateSpec) -> None:
    if spec.name in TEMPLATE_REGISTRY:
        raise RuntimeError(f"Duplicate template registration: {spec.name}")
    TEMPLATE_REGISTRY[spec.name] = spec
```

### 4.2 Registered Templates

```python
register(TemplateSpec(
    name="base",
    path="templates/base.jinja2",
    required_vars=frozenset({"task", "code_files_block"}),
))

register(TemplateSpec(
    name="retry",
    path="templates/retry.jinja2",
    required_vars=frozenset({
        "task", "code_files_block", "previous_code",
        "test_output", "failure_reason", "step_number",
    }),
))

register(TemplateSpec(
    name="repair_feedback",
    path="templates/repair_feedback.jinja2",
    required_vars=frozenset({
        "task", "code_files_block", "error_reasons",
    }),
))

register(TemplateSpec(
    name="contract_elicit",
    path="templates/contract_elicit.jinja2",
    required_vars=frozenset({
        "task", "code_files_block", "contract_schema",
    }),
))

register(TemplateSpec(
    name="contract_code",
    path="templates/contract_code.jinja2",
    required_vars=frozenset({
        "task", "code_files_block", "contract_json",
    }),
))

register(TemplateSpec(
    name="contract_retry",
    path="templates/contract_retry.jinja2",
    required_vars=frozenset({
        "task", "code_files_block", "contract_json", "violations_text",
    }),
))

register(TemplateSpec(
    name="classify",
    path="templates/classify.jinja2",
    required_vars=frozenset({
        "failure_types", "task", "code", "reasoning",
    }),
))
```

### 4.3 Template Hashing (FIX 2 + FIX 3)

Hashes are computed ONCE at startup, stored in an immutable dict, and never recomputed.

The hash is computed from `env.loader.get_source()` -- the exact source Jinja2 uses to compile the template -- NOT from a raw file read.

```python
# Immutable after init_template_hashes() is called. Never modified at runtime.
_template_hashes: dict[str, str] | None = None


def init_template_hashes() -> dict[str, str]:
    """Compute SHA-256 hashes for ALL registered templates. Called ONCE at startup.

    Uses env.loader.get_source() to hash the exact source Jinja2 will render.
    Returns the hash dict and stores it as the immutable module-level lookup.

    Raises:
        RuntimeError: if called more than once (double-init is a bug)
        TemplateNotFoundError: if any registered template cannot be loaded by Jinja2
    """
    global _template_hashes
    if _template_hashes is not None:
        raise RuntimeError(
            "init_template_hashes() called twice. "
            "Template hashes are immutable after startup."
        )

    env = _get_env()
    hashes = {}
    for name, spec in TEMPLATE_REGISTRY.items():
        jinja_name = spec.path.replace("templates/", "")
        try:
            source, _, _ = env.loader.get_source(env, jinja_name)
        except Exception as e:
            raise TemplateNotFoundError(
                f"Cannot load template '{name}' ({jinja_name}) via Jinja2 loader: {e}"
            ) from e
        hashes[name] = hashlib.sha256(source.encode("utf-8")).hexdigest()

    _template_hashes = hashes  # store once, read forever
    return dict(hashes)  # return a copy so caller can't mutate


def get_template_hash(template_name: str) -> str:
    """Get the precomputed hash for a template. Must call init_template_hashes() first."""
    if _template_hashes is None:
        raise RuntimeError(
            "get_template_hash() called before init_template_hashes(). "
            "Template hashes must be initialized at startup."
        )
    if template_name not in _template_hashes:
        raise TemplateNotFoundError(
            f"No hash for template '{template_name}'. "
            f"Known: {sorted(_template_hashes.keys())}"
        )
    return _template_hashes[template_name]
```

### 4.4 Jinja2 Environment

```python
_env: Environment | None = None

def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(BASE_DIR / "templates")),
            undefined=StrictUndefined,     # CRITICAL: missing var = hard error
            autoescape=False,              # not HTML
            keep_trailing_newline=True,
        )
    return _env
```

### 4.5 Render Function (The Critical Path)

```python
def render(template_name: str, variables: dict[str, str]) -> str:
    """Render a registered template with strict validation.

    Raises:
        TemplateNotFoundError: template_name not in TEMPLATE_REGISTRY
        TemplateMissingVarError: required var not in variables
        TemplateExtraVarError: variables contains keys not in required_vars
        jinja2.UndefinedError: Jinja2 StrictUndefined caught a missing var at render time
    """
    # Step 1: Registry lookup
    spec = TEMPLATE_REGISTRY.get(template_name)
    if spec is None:
        raise TemplateNotFoundError(
            f"Template '{template_name}' is not registered. "
            f"Known templates: {sorted(TEMPLATE_REGISTRY.keys())}"
        )

    # Step 2: Variable validation BEFORE render
    provided = frozenset(variables.keys())
    missing = spec.required_vars - provided
    if missing:
        raise TemplateMissingVarError(
            f"Template '{template_name}' requires variables {sorted(missing)} "
            f"but they were not provided. "
            f"Required: {sorted(spec.required_vars)}, Provided: {sorted(provided)}"
        )
    extra = provided - spec.required_vars
    if extra:
        raise TemplateExtraVarError(
            f"Template '{template_name}' received unexpected variables {sorted(extra)}. "
            f"Required: {sorted(spec.required_vars)}, Provided: {sorted(provided)}"
        )

    # Step 3: Get precomputed hash for provenance
    template_hash = get_template_hash(template_name)

    # Step 4: Log what we're doing
    _tpl_log.info(
        "TEMPLATE LOADED: %s (hash=%s)\n  REQUIRED VARS: %s\n  PROVIDED VARS: %s",
        spec.path, template_hash[:12], sorted(spec.required_vars), sorted(provided)
    )

    # Step 5: Render (StrictUndefined is the second safety net)
    env = _get_env()
    template = env.get_template(spec.path.replace("templates/", ""))
    rendered = template.render(**variables)

    return rendered


def render_with_metadata(template_name: str, variables: dict[str, str]) -> tuple[str, dict]:
    """Render and return (rendered_text, metadata_dict).

    metadata_dict contains template_name, template_hash, variables -- everything
    needed for prompt logging.
    """
    rendered = render(template_name, variables)
    template_hash = get_template_hash(template_name)
    metadata = {
        "template_name": template_name,
        "template_hash": template_hash,
        "variables": dict(variables),
        "rendered_length": len(rendered),
    }
    return rendered, metadata
```

### 4.6 Custom Exceptions

```python
class TemplateError(Exception):
    """Base class for all template system errors."""
    pass

class TemplateNotFoundError(TemplateError):
    pass

class TemplateMissingVarError(TemplateError):
    pass

class TemplateExtraVarError(TemplateError):
    pass
```

### 4.7 Template File Contents

(Unchanged from v2 -- all seven template files as specified in v2 section 4.7.)

### 4.8 Template Rules (Enforced -- FIX 6)

1. **Limited logic allowed in templates**: `{% if %}` / `{% elif %}` / `{% else %}` / `{% endif %}` are permitted for optional sections. Loops (`{% for %}`), macros (`{% macro %}`), and complex logic (`{% call %}`, `{% filter %}`, `{% set %}`, `{% block %}`) are forbidden. Enforced by preflight lint:

   ```python
   # Allowed: if, elif, else, endif
   # Forbidden: for, endfor, macro, endmacro, call, filter, set, block, endblock, extends, import
   FORBIDDEN_TEMPLATE_TAGS = frozenset({
       "for", "endfor", "macro", "endmacro", "call", "endcall",
       "filter", "endfilter", "set", "block", "endblock",
       "extends", "import", "from",
   })

   def validate_template_allowed_logic(template_path: Path) -> None:
       """Check that template uses only allowed Jinja2 tags."""
       content = template_path.read_text()
       # Find all {% tag_name ... %} blocks
       tags = re.findall(r'{%-?\s*(\w+)', content)
       for tag in tags:
           if tag in FORBIDDEN_TEMPLATE_TAGS:
               raise TemplateError(
                   f"Template {template_path} uses forbidden tag '{{% {tag} %}}'. "
                   f"Only if/elif/else/endif are allowed. "
                   f"Forbidden: {sorted(FORBIDDEN_TEMPLATE_TAGS)}"
               )
   ```

2. **StrictUndefined is always on**: The Environment is created once and never reconfigured.

3. **All templates registered**: Any template file in `templates/` that is NOT in `TEMPLATE_REGISTRY` causes a preflight error.

### 4.9 Preflight Template Validation

Called once at startup, BEFORE any experiment runs:

```python
def preflight_validate_templates(config: ExperimentConfig) -> None:
    """Validate all templates. Raises on ANY issue. Called once at startup."""

    # 1. Check every registered template file exists
    for name, spec in TEMPLATE_REGISTRY.items():
        full_path = BASE_DIR / spec.path
        if not full_path.exists():
            raise TemplateNotFoundError(
                f"Registered template '{name}' points to {full_path} which does not exist"
            )

    # 2. Check no unregistered templates exist
    template_dir = BASE_DIR / "templates"
    on_disk = {p.name for p in template_dir.glob("*.jinja2")}
    registered_files = {Path(spec.path).name for spec in TEMPLATE_REGISTRY.values()}
    unregistered = on_disk - registered_files
    if unregistered:
        raise TemplateError(
            f"Unregistered template files found: {unregistered}. "
            f"Every .jinja2 file must be registered in TEMPLATE_REGISTRY."
        )

    # 3. Validate template logic rules (FIX 6: if/else allowed, loops/macros forbidden)
    for name, spec in TEMPLATE_REGISTRY.items():
        validate_template_allowed_logic(BASE_DIR / spec.path)

    # 4. Validate every condition's template references exist in registry
    for cond_name, cond_cfg in config.conditions.items():
        for field in ("template", "retry_template", "next_template"):
            tpl_name = getattr(cond_cfg, field)
            if tpl_name is not None and tpl_name not in TEMPLATE_REGISTRY:
                raise TemplateError(
                    f"Condition '{cond_name}'.{field} = '{tpl_name}' "
                    f"not in TEMPLATE_REGISTRY"
                )

    # 5. Dry-render all templates with placeholder values to verify Jinja2 syntax
    env = _get_env()
    for name, spec in TEMPLATE_REGISTRY.items():
        try:
            template = env.get_template(spec.path.replace("templates/", ""))
            placeholders = {var: f"__PLACEHOLDER_{var}__" for var in spec.required_vars}
            template.render(**placeholders)
        except Exception as e:
            raise TemplateError(
                f"Template '{name}' failed dry-render validation: {e}"
            ) from e

    # 6. Compute and store all template hashes (FIX 2: once, immutable)
    hashes = init_template_hashes()
    _tpl_log.info(
        "PREFLIGHT: All %d templates validated OK. Hashes: %s",
        len(TEMPLATE_REGISTRY),
        {k: v[:12] for k, v in hashes.items()},
    )
```

### 4.10 Prompt Logging

```python
def log_rendered_prompt(template_name: str, template_hash: str,
                        variables: dict, rendered: str) -> dict:
    """Build a prompt log record with full provenance."""
    record = {
        "template_name": template_name,
        "template_hash": template_hash,
        "variables": variables,
        "rendered_prompt": rendered,
        "rendered_length": len(rendered),
    }
    _tpl_log.info(
        "PROMPT RENDERED: template=%s hash=%s vars=%s len=%d",
        template_name, template_hash[:12], sorted(variables.keys()), len(rendered)
    )
    return record
```

---

## 5. RETRY + TRAJECTORY SYSTEM (PART 1)

### 5.1 Extended Event Schema

Every trajectory event emitted by the retry harness MUST include these new fields:

```python
{
    # Existing fields (unchanged)
    "pass": bool,
    "score": float,
    "code": str,
    "reasoning": str,
    # ...

    # NEW REQUIRED FIELDS
    "step": int,                       # 0-indexed step number
    "is_retry": bool,                  # False for step 0, True for step > 0
    "retry_reason": str,               # "" for step 0, else structured reason
    "prev_failure_type": str | None,   # None for step 0, else from classifier
}
```

### 5.2 Extended Event Emission

In `execution.py:_emit_metrics_event()`, add the new fields:

```python
{
    # ... existing fields ...
    "step": ev.get("step", 0),
    "is_retry": ev.get("is_retry", False),
    "retry_reason": ev.get("retry_reason", ""),
    "prev_failure_type": ev.get("prev_failure_type"),
}
```

### 5.3 Modified Retry Loop -- Explicit Condition (FIX 5)

The `condition` parameter is passed explicitly by the caller. No inference from boolean flags.

**Signature change:**

```python
# OLD (v2 -- implicit inference):
def run_retry_harness(case, model, config, max_iterations=5,
                      use_contract=False, use_adaptive=False,
                      use_alignment=False, ...):
    condition = ...  # inferred from flags  <-- DELETED

# NEW (v3 -- explicit):
def run_retry_harness(case, model, condition: str, config: ExperimentConfig,
                      eval_model=None):
    """Run retry harness. condition is passed explicitly by the caller.

    Args:
        case: benchmark case dict
        model: model name for generation
        condition: one of the RETRY_CONDITIONS (e.g., "retry_no_contract")
        config: frozen experiment config
        eval_model: model for LEG evaluator calls (default: use `model`)
    """
```

**Caller in `runner.py:_run_one_inner()`:**

```python
# OLD (v2):
if condition == "retry_no_contract":
    from retry_harness import run_retry_harness
    return run_retry_harness(case, model, use_contract=False, eval_model=LEG_EVAL_MODEL)
if condition == "retry_with_contract":
    from retry_harness import run_retry_harness
    return run_retry_harness(case, model, use_contract=True, eval_model=LEG_EVAL_MODEL)
# ... etc

# NEW (v3):
if condition in RETRY_CONDITIONS:
    from retry_harness import run_retry_harness
    return run_retry_harness(
        case, model, condition=condition, config=config, eval_model=LEG_EVAL_MODEL
    )
```

**Inside `run_retry_harness`, condition-specific behavior reads from config:**

```python
def run_retry_harness(case, model, condition: str, config: ExperimentConfig,
                      eval_model=None):
    cond_cfg = config.conditions[condition]
    max_steps = config.retry.max_steps

    for step in range(max_steps):
        if step == 0:
            tpl_name = cond_cfg.template
            prompt, prompt_meta = render_with_metadata(tpl_name, {
                "task": case["task"],
                "code_files_block": _format_code_files(case["code_files_contents"]),
            })
            is_retry = False
            retry_reason = ""
            prev_failure_type = None
        else:
            prev_entry = trajectory[-1]
            prev_failure_type = prev_entry.get("failure_type")
            retry_reason = _build_retry_reason(prev_entry)

            tpl_name = cond_cfg.retry_template
            prompt, prompt_meta = render_with_metadata(tpl_name, {
                "task": case["task"],
                "code_files_block": _format_code_files(case["code_files_contents"]),
                "previous_code": prev_entry["code"],
                "test_output": prev_entry["test_output"],
                "failure_reason": retry_reason,
                "step_number": str(step),
            })
            is_retry = True

        # --- CALL MODEL ---
        raw_output = call_model(prompt, model=model)

        # --- PARSE, EVALUATE, CLASSIFY (unchanged) ---
        ...

        # --- LOG EVENT WITH NEW FIELDS ---
        step_entry = {
            # ... existing fields ...
            "step": step,
            "is_retry": is_retry,
            "retry_reason": retry_reason,
            "prev_failure_type": prev_failure_type,
            "template_name": prompt_meta["template_name"],
            "template_hash": prompt_meta["template_hash"],
        }
        trajectory.append(step_entry)

        if ev["pass"]:
            break
```

### 5.4 `_build_retry_reason` Helper

```python
def _build_retry_reason(prev_entry: dict) -> str:
    """Build a structured retry reason from the previous trajectory entry."""
    parts = []
    ft = prev_entry.get("failure_type")
    if ft:
        parts.append(f"failure_type={ft}")
    err = prev_entry.get("error", {})
    cat = err.get("category")
    if cat:
        parts.append(f"error_category={cat}")
    score = prev_entry.get("score", 0)
    parts.append(f"prev_score={score:.2f}")
    test_out = prev_entry.get("test_output", "")
    if test_out:
        parts.append(f"test_summary={test_out[:200]}")
    return "; ".join(parts) if parts else "previous_attempt_failed"
```

### 5.5 Config-Driven Parameters

| Parameter | Config Path | Current Hardcoded Value |
|---|---|---|
| `max_steps` | `config.retry.max_steps` | 5 |
| `timeout_total_seconds` | `config.execution.timeout_total_seconds` | 360 |
| `timeout_per_step_seconds` | `config.execution.timeout_per_step_seconds` | 60 |

Module-level constants become defaults used ONLY when config is not provided (backward compat for tests).

---

## 6. INTEGRATION FLOW

### 6.1 Startup Sequence

```
1. Parse CLI args
2. load_config("experiment.yaml")          -> ExperimentConfig (frozen, version-checked)
3. preflight_validate_templates(config)     -> validates + init_template_hashes() (once, immutable)
4. preflight_verify_tests(cases)            -> HARD ERROR if any test missing
5. validate_run(cases, conditions)          -> HARD ERROR if incompatible pairs
6. log_resolved_config(config, run_dir)     -> config_resolved.yaml on disk
7. init_run_log(model, log_dir)             -> RunLogger active
8. Begin experiment loop
```

### 6.2 Prompt Construction Flow

(Unchanged from v2 section 6.2.)

### 6.3 How Config Selects Templates

For **simple conditions** (baseline, diagnostic, guardrail, etc.):
1. `config.conditions["baseline"].template` -> `"base"`
2. Render `"base"` template -> base prompt text
3. For nudge conditions: apply nudge operator -> modified text

For **retry conditions** (retry_no_contract, retry_with_contract, etc., repair_loop):
1. Step 0: `cond_cfg.template` -> `"base"`
2. Step 1+: `cond_cfg.retry_template` -> `"retry"` (or `"repair_feedback"` for repair_loop)

For **multistep conditions** (contract_gated):
1. Step 1: `cond_cfg.template` -> `"contract_elicit"`
2. Step 2: `cond_cfg.next_template` -> `"contract_code"`
3. Step 3: `cond_cfg.retry_template` -> `"contract_retry"`

### 6.4 Variable Construction

(Unchanged from v2 section 6.4.)

---

## 7. VALIDATION LOGIC (Comprehensive)

### 7.1 Config Validation Matrix

| Check | What | Error |
|---|---|---|
| Missing top-level key | `raw.keys() >= REQUIRED_TOP_KEYS` | `ConfigError("Missing required top-level keys: ...")` |
| Unknown top-level key | `raw.keys() <= REQUIRED_TOP_KEYS` | `ConfigError("Unknown top-level keys: ...")` |
| Wrong config version | `experiment.version != CURRENT_CONFIG_VERSION` | `ConfigError("...not compatible with this version...")` |
| Missing section key | e.g., `retry.enabled` absent | `ConfigError("retry.enabled is required")` |
| Wrong type | `retry.max_steps` is str | `ConfigError("retry.max_steps must be int, got str")` |
| Out of range | `retry.max_steps` = 0 | `ConfigError("retry.max_steps must be in [1, 20]")` |
| Invalid enum | `retry.strategy` = "tree" | `ConfigError("retry.strategy must be one of ...")` |
| Invalid condition name | `conditions.foo_bar` | `ConfigError("...not a valid condition...")` |
| Missing condition template | `conditions.baseline` has no `template` | `ConfigError("...template is required")` |
| Unknown condition key | `conditions.baseline.bogus` | `ConfigError("Unknown keys in ...")` |
| Template ref not in registry | `conditions.baseline.template = "x"` | `ConfigError("...not in TEMPLATE_REGISTRY")` |
| Simple cond has retry_template | `conditions.baseline.retry_template = "retry"` | `ConfigError("...simple condition...MUST NOT have retry_template")` |
| Retry cond missing retry_template | `conditions.retry_no_contract` has no retry_template | `ConfigError("...retry condition...MUST have retry_template")` |
| Retry cond has next_template | `conditions.retry_no_contract.next_template = "x"` | `ConfigError("...retry condition...MUST NOT have next_template")` |
| Multistep cond missing next_template | `conditions.contract_gated` has no next_template | `ConfigError("...multistep condition...MUST have next_template")` |
| Multistep cond missing retry_template | `conditions.contract_gated` has no retry_template | `ConfigError("...multistep condition...MUST have retry_template")` |
| File missing | `execution.cases_file` doesn't exist | `ConfigError("...does not exist")` |

### 7.2 Template Validation Matrix

| Check | What | Error |
|---|---|---|
| Template not registered | `render("foo", ...)` | `TemplateNotFoundError` |
| Missing variable | `render("retry", {"task": ...})` | `TemplateMissingVarError` |
| Extra variable | `render("base", {"task": ..., "extra": ...})` | `TemplateExtraVarError` |
| Template file missing | registered but file gone | `TemplateNotFoundError` at preflight |
| Forbidden logic in template | `{% for %}` in `.jinja2` file | `TemplateError` at preflight |
| Unregistered file | `templates/orphan.jinja2` exists | `TemplateError` at preflight |
| Jinja2 syntax error | Malformed `{{ }}` | `TemplateError` at preflight dry-render |
| Jinja2 StrictUndefined | Template references `{{ typo }}` | `jinja2.UndefinedError` at render time |
| Hash before init | `get_template_hash()` before startup | `RuntimeError` |
| Double init | `init_template_hashes()` called twice | `RuntimeError` |

### 7.3 Runtime Validation

At every template render call:
1. Registry lookup (TemplateNotFoundError)
2. Exact variable set match (TemplateMissingVarError / TemplateExtraVarError)
3. Jinja2 StrictUndefined (backup safety net)

---

## 8. LOGGING SPEC

(Unchanged from v2 sections 8.1-8.4.)

---

## 9. FAILURE MODES ELIMINATED

| Failure Mode | How Eliminated |
|---|---|
| Missing template variable -> silent default | `StrictUndefined` + pre-render set comparison = TWO independent checks. |
| Wrong template loaded -> unnoticed | Config explicitly names templates per condition. Log shows template name + hash. |
| Variable name typo -> silent bug | `TemplateExtraVarError` / `TemplateMissingVarError`. |
| Config drift between runs | `config_resolved.yaml` per run. Frozen dataclass. |
| Template file changed between runs | `template_hash` logged per prompt. Hashed via Jinja2 loader source (FIX 3). |
| Stale template hash | Hashes computed once at startup into immutable dict. No lazy cache (FIX 2). |
| Invalid condition-template combo | Structural invariants enforced: simple/retry/multistep categories (FIX 1). |
| Unknown config version | `experiment.version` checked on load. Reject != CURRENT_CONFIG_VERSION (FIX 4). |
| Implicit condition inference | `condition` passed explicitly to retry harness. No flag-based inference (FIX 5). |
| Hardcoded condition-template mapping | Mapping lives in config YAML, not in Python code. |
| Config depends on runtime code | Condition validation uses `constants.py`, a zero-dependency module. |

---

## 10. FULL TEST PLAN

### 10.1 Template System Tests (`tests/test_templates.py`)

```python
# T1-T8: Unchanged from v2 (missing var, extra var, unknown template, correct render,
#         empty var, StrictUndefined, retry render, all templates dry-render)

# T9: Unregistered template file detected by preflight
def test_preflight_detects_unregistered_file(tmp_path):
    ...

# T10: Forbidden logic in template detected by preflight (UPDATED for FIX 6)
def test_preflight_detects_forbidden_logic(tmp_path):
    # {% for %} -> error
    # {% macro %} -> error
    # {% set %} -> error
    ...

# T10b: Allowed logic in template passes preflight (NEW for FIX 6)
def test_preflight_allows_if_blocks(tmp_path):
    # {% if x %} ... {% endif %} -> OK
    ...

# T11: Template hash is deterministic
def test_template_hash_deterministic():
    # init, get, reset module state, init again -> same hash
    ...

# T12: Template hash changes when file changes
def test_template_hash_changes_on_file_change(tmp_path):
    ...

# T13: render_with_metadata returns correct metadata (unchanged)
def test_render_with_metadata():
    ...

# T14: get_template_hash before init raises RuntimeError (NEW for FIX 2)
def test_get_hash_before_init_raises():
    # Reset module state, then call get_template_hash -> RuntimeError
    ...

# T15: init_template_hashes called twice raises RuntimeError (NEW for FIX 2)
def test_double_init_raises():
    ...

# T16: Hash uses Jinja2 loader source (NEW for FIX 3)
def test_hash_matches_jinja_source():
    # Verify hash == sha256(env.loader.get_source(...))
    ...
```

### 10.2 Config System Tests (`tests/test_config.py`)

```python
# C1-C9: Unchanged from v2 (missing field, wrong type, unknown field, immutable,
#         invalid condition, missing template key, unknown condition key,
#         template not in registry, max_steps range)

# C10: Valid config loads successfully (UPDATED: now includes version)
def test_valid_config_loads():
    config = load_config(test_config_path)
    assert config.version == 1
    assert config.name == "retry_ablation_v2"
    ...

# C11-C14: Unchanged from v2 (resolved config, missing top-level, unknown top-level, empty conditions)

# C15: Wrong config version rejected (NEW for FIX 4)
def test_wrong_config_version_rejected():
    raw = valid_config_dict()
    raw["experiment"]["version"] = 999
    with pytest.raises(ConfigError, match="not compatible"):
        _validate_and_build(raw)

# C16: Missing config version rejected (NEW for FIX 4)
def test_missing_config_version_rejected():
    raw = valid_config_dict()
    del raw["experiment"]["version"]
    with pytest.raises(ConfigError, match="version"):
        _validate_and_build(raw)

# C17: Simple condition with retry_template rejected (NEW for FIX 1)
def test_simple_condition_rejects_retry_template():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["retry_template"] = "retry"
    with pytest.raises(ConfigError, match="simple condition.*MUST NOT have retry_template"):
        _validate_and_build(raw)

# C18: Simple condition with next_template rejected (NEW for FIX 1)
def test_simple_condition_rejects_next_template():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["next_template"] = "contract_code"
    with pytest.raises(ConfigError, match="simple condition.*MUST NOT have next_template"):
        _validate_and_build(raw)

# C19: Retry condition missing retry_template rejected (NEW for FIX 1)
def test_retry_condition_requires_retry_template():
    raw = valid_config_dict()
    del raw["conditions"]["retry_no_contract"]["retry_template"]
    with pytest.raises(ConfigError, match="retry condition.*MUST have retry_template"):
        _validate_and_build(raw)

# C20: Retry condition with next_template rejected (NEW for FIX 1)
def test_retry_condition_rejects_next_template():
    raw = valid_config_dict()
    raw["conditions"]["retry_no_contract"]["next_template"] = "contract_code"
    with pytest.raises(ConfigError, match="retry condition.*MUST NOT have next_template"):
        _validate_and_build(raw)

# C21: Multistep condition missing next_template rejected (NEW for FIX 1)
def test_multistep_condition_requires_next_template():
    raw = valid_config_dict()
    del raw["conditions"]["contract_gated"]["next_template"]
    with pytest.raises(ConfigError, match="multistep condition.*MUST have next_template"):
        _validate_and_build(raw)

# C22: Multistep condition missing retry_template rejected (NEW for FIX 1)
def test_multistep_condition_requires_retry_template():
    raw = valid_config_dict()
    del raw["conditions"]["contract_gated"]["retry_template"]
    with pytest.raises(ConfigError, match="multistep condition.*MUST have retry_template"):
        _validate_and_build(raw)
```

### 10.3 Constants Tests (`tests/test_constants.py`)

```python
# K1-K3: Unchanged from v2 (frozen, unique labels, every condition has label)

# K4: Condition categories are exhaustive (NEW for FIX 1)
def test_condition_categories_exhaustive():
    from constants import VALID_CONDITIONS, RETRY_CONDITIONS, MULTISTEP_CONDITIONS, SIMPLE_CONDITIONS
    assert RETRY_CONDITIONS | MULTISTEP_CONDITIONS | SIMPLE_CONDITIONS == VALID_CONDITIONS

# K5: Condition categories are non-overlapping (NEW for FIX 1)
def test_condition_categories_non_overlapping():
    from constants import RETRY_CONDITIONS, MULTISTEP_CONDITIONS, SIMPLE_CONDITIONS
    assert not (RETRY_CONDITIONS & MULTISTEP_CONDITIONS)
    assert not (RETRY_CONDITIONS & SIMPLE_CONDITIONS)
    assert not (MULTISTEP_CONDITIONS & SIMPLE_CONDITIONS)

# K6: CURRENT_CONFIG_VERSION is an int (NEW for FIX 4)
def test_config_version_is_int():
    from constants import CURRENT_CONFIG_VERSION
    assert isinstance(CURRENT_CONFIG_VERSION, int)
    assert CURRENT_CONFIG_VERSION >= 1
```

### 10.4 Retry Trajectory Tests (`tests/test_retry_trajectory.py`)

```python
# R1-R9: Unchanged from v2 (step 0 not retry, step 1+ is retry, prev_failure_type,
#         step increments, max_steps from config, correct template, retry_reason,
#         events include step, trajectory has template_hash)

# R10: Condition passed explicitly -- no flag inference (NEW for FIX 5)
def test_condition_passed_explicitly():
    # Verify run_retry_harness signature requires `condition: str`
    import inspect
    sig = inspect.signature(run_retry_harness)
    assert "condition" in sig.parameters
    assert sig.parameters["condition"].annotation == str
    # Verify no use_contract/use_adaptive/use_alignment params
    assert "use_contract" not in sig.parameters
    assert "use_adaptive" not in sig.parameters
    assert "use_alignment" not in sig.parameters

# R11: Condition name appears in trajectory entries (NEW for FIX 5)
def test_trajectory_includes_condition():
    result = run_retry_harness(
        mock_case, "mock", condition="retry_no_contract", config=mock_config
    )
    # The condition should be in the final result
    assert result[1] == "retry_no_contract"
```

### 10.5 Integration Tests (`tests/test_integration_config_template.py`)

```python
# I1-I9: Unchanged from v2

# I10: Structural invariants enforced end-to-end (NEW for FIX 1)
def test_structural_invariants_e2e():
    # Load valid config -> all conditions pass structural checks
    config = load_config(test_config_path)
    for cond_name, cond_cfg in config.conditions.items():
        if cond_name in SIMPLE_CONDITIONS:
            assert cond_cfg.retry_template is None
            assert cond_cfg.next_template is None
        elif cond_name in RETRY_CONDITIONS:
            assert cond_cfg.retry_template is not None
            assert cond_cfg.next_template is None
        elif cond_name in MULTISTEP_CONDITIONS:
            assert cond_cfg.retry_template is not None
            assert cond_cfg.next_template is not None
```

---

## 11. BACKWARD COMPATIBILITY

### What Changes for Existing Code

1. **`runner.py`**: Imports from `constants.py`. Gains `--config` argument. Passes `condition` explicitly to `run_retry_harness()` instead of boolean flags.

2. **`execution.py:build_prompt()`**: Gains optional `use_templates: bool = False`. When `True`, routes through `templates.render()`. When `False` (default), uses existing f-string path.

3. **`retry_harness.py:run_retry_harness()`**: New signature: `(case, model, condition, config, eval_model=None)`. Old boolean-flag parameters (`use_contract`, `use_adaptive`, `use_alignment`) are removed. Existing callers in `runner.py` are updated to pass condition explicitly.

4. **All existing 68+ retry harness tests**: Must be updated to pass `condition` explicitly instead of boolean flags. This is a mechanical change.

5. **Nudge-based conditions**: Unchanged. They post-process the base template output.

### Migration Strategy

Phase 1: Ship `constants.py`, `config.py`, `templates.py`, all `.jinja2` files, and tests. Update `runner.py` to pass condition explicitly. `use_templates=False` default.
Phase 2: Flip `use_templates=True` in ablation mode only. Verify all ablation runs match.
Phase 3: Remove legacy f-string paths once validated.
