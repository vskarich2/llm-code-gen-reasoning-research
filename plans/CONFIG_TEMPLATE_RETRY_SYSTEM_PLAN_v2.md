# DESIGN PLAN: Retry + Trajectory, Config System, Templating System

**Version:** v2
**Date:** 2026-03-24
**Status:** Design complete, pending implementation
**Depends on:** retry_harness.py (implemented), runner.py, execution.py, evaluator.py, prompts.py
**Supersedes:** CONFIG_TEMPLATE_RETRY_SYSTEM_PLAN_v1.md

---

## CHANGELOG (v1 -> v2)

| Fix | What Changed | Rationale |
|---|---|---|
| FIX 1 | Removed `prompt_vars` section from config and `PromptVarsConfig` dataclass | Template variable requirements exist ONLY in `TemplateSpec.required_vars`. One source of truth. |
| FIX 2 | Moved condition-to-template mapping from hardcoded `CONDITION_TEMPLATE_MAP` into config YAML | No hidden logic. Config is the single authority for which template each condition uses. |
| FIX 3 | Removed "template must contain placeholder string" check from preflight dry-render | Over-strict and brittle. A template may legitimately not render a variable in output (e.g., used in a conditional context). StrictUndefined + pre-render var set check are sufficient. |
| FIX 4 | Added template versioning: SHA-256 hash of each template file, logged with every rendered prompt | Required for reproducibility -- detects template file changes between runs. |
| FIX 5 | Removed `from runner import VALID_CONDITIONS`. Created `constants.py` as shared source of truth for condition names | Config must not depend on runtime code. Dependency arrow: runner -> constants, config -> constants. |
| FIX 6 | Added full variable dictionary to prompt log record | Full variable capture enables complete prompt reconstruction from logs. |

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
| `constants.py` | Shared constants: `VALID_CONDITIONS`, condition labels (FIX 5) |
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
| `runner.py` | Import conditions from `constants.py` instead of defining locally; load config at startup |
| `retry_harness.py` | Add `step`, `is_retry`, `retry_reason`, `prev_failure_type` to trajectory events |
| `execution.py` | Route through template renderer; emit extended events |
| `live_metrics.py` | Accept extended event fields |
| `ablation_config.yaml` -> `experiment.yaml` | Replaced with strict schema |

---

## 2. SHARED CONSTANTS MODULE (FIX 5)

### 2.1 Purpose

Config validation needs the set of valid conditions. `runner.py` also needs it. Neither should depend on the other. Both import from `constants.py`.

### 2.2 File: `constants.py`

```python
"""Shared constants for T3 benchmark.

This module is the SOLE source of truth for condition names and labels.
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
    f"FATAL: Duplicate condition labels detected. "
    f"Labels: {[v for v in COND_LABELS.values() if list(COND_LABELS.values()).count(v) > 1]}"
)
```

### 2.3 Migration

`runner.py` deletes its local `ALL_CONDITIONS`, `VALID_CONDITIONS`, `COND_LABELS` and replaces with:
```python
from constants import ALL_CONDITIONS, VALID_CONDITIONS, COND_LABELS
```

`config.py` imports:
```python
from constants import VALID_CONDITIONS
```

No circular dependency. `constants.py` imports nothing from the project.

---

## 3. CONFIG SYSTEM (PART 2)

### 3.1 Schema Definition

File: `experiment.yaml`

```yaml
experiment:
  name: "retry_ablation_v2"          # str, required
  models:                             # list[str], required, min 1
    - "gpt-4o-mini"
    - "gpt-5-mini"

conditions:                           # dict[str, ConditionConfig], required, min 1 entry
  baseline:
    template: "base"                  # str, required, must match TEMPLATE_REGISTRY key
  diagnostic:
    template: "base"                  # nudge conditions render base, then post-process
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
    retry_template: "repair_feedback" # template for attempt 2+
  contract_gated:
    template: "contract_elicit"       # step 1: elicit contract
    next_template: "contract_code"    # step 2: generate code from contract
    retry_template: "contract_retry"  # step 3: retry after gate violation
  retry_no_contract:
    template: "base"
    retry_template: "retry"           # template for step 1+
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
    name: str
    models: tuple[str, ...]
    conditions: dict[str, ConditionConfig]   # condition_name -> ConditionConfig
    retry: RetryConfig
    execution: ExecutionConfig
    logging: LoggingConfig
```

**Removed from v1**: `TemplatesConfig`, `PromptVarsConfig`. Template paths are derived from registry lookups via `ConditionConfig.template`. Variable requirements live solely in `TemplateSpec.required_vars`.

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

4. **Experiment section validation**:
   ```python
   EXPERIMENT_REQUIRED = {"name": str, "models": list}
   # validate types, reject unknown keys, require models non-empty
   ```

5. **Conditions section validation**:
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

       # e) Validate all template references exist in TEMPLATE_REGISTRY
       from templates import TEMPLATE_REGISTRY
       for key in ("template", "retry_template", "next_template"):
           tpl_name = cond_raw.get(key)
           if tpl_name is not None and tpl_name not in TEMPLATE_REGISTRY:
               raise ConfigError(
                   f"conditions.{cond_name}.{key} = '{tpl_name}' does not match "
                   f"any registered template. Known: {sorted(TEMPLATE_REGISTRY.keys())}"
               )

       # f) Type check all values are str
       for key, val in cond_raw.items():
           if not isinstance(val, str):
               raise ConfigError(
                   f"conditions.{cond_name}.{key} must be str, got {type(val).__name__}"
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

The runner no longer contains any condition-to-template mapping. It reads from config:

```python
# In execution.py or wherever prompt is built:
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

At the start of every run, the exact config is serialized to disk:

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

**Invariant**: `config_resolved.yaml` in every run directory is the EXACT config that produced that run's data. No exceptions.

### 3.6 Integration Point

In `runner.py:main()` and `runner.py:_run_ablation_mode()`:

```python
# At top of main(), BEFORE any other work:
config = load_config(BASE_DIR / args.config)  # new --config arg, default "experiment.yaml"
# All downstream code receives `config`, never reads raw YAML again
```

The config object is passed explicitly -- never stored in module-level globals. Functions that need it receive it as an argument.

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
# Adding a template without registering it is a bug.
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

### 4.3 Template Hashing (FIX 4)

```python
# Cache: template_name -> sha256 hex digest of source file
_template_hashes: dict[str, str] = {}

def compute_template_hash(spec: TemplateSpec) -> str:
    """Compute SHA-256 of the template source file. Cached after first call."""
    if spec.name in _template_hashes:
        return _template_hashes[spec.name]
    full_path = BASE_DIR / spec.path
    content = full_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    _template_hashes[spec.name] = digest
    return digest

def compute_all_template_hashes() -> dict[str, str]:
    """Compute and cache hashes for all registered templates. Called at startup."""
    result = {}
    for name, spec in TEMPLATE_REGISTRY.items():
        result[name] = compute_template_hash(spec)
    return result

def clear_template_hash_cache() -> None:
    """Clear hash cache. Used in tests when template files change."""
    _template_hashes.clear()
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

    # Step 3: Compute template hash for provenance
    template_hash = compute_template_hash(spec)

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
    spec = TEMPLATE_REGISTRY[template_name]  # will KeyError if missing; render() gives better msg
    rendered = render(template_name, variables)
    template_hash = compute_template_hash(spec)
    metadata = {
        "template_name": template_name,
        "template_hash": template_hash,
        "variables": dict(variables),       # FIX 6: full variable dictionary
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

**`templates/base.jinja2`**:
```
{{ task }}

{{ code_files_block }}
```

**`templates/retry.jinja2`**:
```
{{ task }}

{{ code_files_block }}

--- PREVIOUS ATTEMPT (step {{ step_number }}) ---

Your previous code:
{{ previous_code }}

Test results:
{{ test_output }}

Failure reason: {{ failure_reason }}

Fix the code. Return corrected code only.
```

**`templates/repair_feedback.jinja2`**:
```
{{ task }}

{{ code_files_block }}

Your previous attempt FAILED with:
{{ error_reasons }}

Fix and return corrected code.
```

**`templates/contract_elicit.jinja2`**:
```
{{ task }}

{{ code_files_block }}

Before writing any code, analyze this codebase and identify the causal dependencies.

Produce an Execution Contract as JSON with this exact schema:

{{ contract_schema }}

Return ONLY the JSON contract. Do not write code yet.
```

**`templates/contract_code.jinja2`**:
```
{{ task }}

{{ code_files_block }}

You committed to this Execution Contract:

{{ contract_json }}

Write refactored code that satisfies ALL contract terms. Specifically:
- Modify ONLY the functions listed in must_change
- Do NOT modify functions listed in must_not_change
- Implement ALL required_effects
- Maintain ALL invariants
- Respect the ordering, retry, and rollback constraints

Return the code only.
```

**`templates/contract_retry.jinja2`**:
```
{{ task }}

{{ code_files_block }}

Your code violates the Execution Contract you committed to.

VIOLATIONS:
{{ violations_text }}

Your original contract:
{{ contract_json }}

Fix EACH violation specifically. Do not change anything else.
Return corrected code only.
```

**`templates/classify.jinja2`**:
```
You are evaluating whether a developer's REASONING correctly identifies the root cause of a software bug.

You are ONLY evaluating reasoning quality. You are NOT judging whether the code is correct.
The code may be correct or incorrect -- that is NOT your task.

Do NOT assume the code is correct or incorrect based on appearance.
Do NOT infer correctness from likely execution success.
Focus ONLY on whether the reasoning correctly identifies the bug mechanism and proposes a fix consistent with that mechanism.

# Your Task

Determine TWO things:

1. **reasoning_correct**: Does the reasoning correctly identify the TRUE failure mechanism?
   - TRUE if the reasoning identifies the correct root cause AND explains how the bug manifests
   - FALSE if the reasoning is wrong, vague, irrelevant, or identifies the wrong mechanism

2. **failure_type**: What type of failure mechanism does this bug involve?
   Choose EXACTLY one from:
   {{ failure_types }}

# Inputs

## Task Description
{{ task }}

## Developer's Reasoning
{{ reasoning }}

## Code Produced by Developer
```python
{{ code }}
```

# Rules
- Evaluate ONLY reasoning quality -- whether the developer understood the bug
- Do NOT judge whether the code would pass or fail tests
- A developer can have perfect reasoning but write broken code, or vice versa
- Be conservative: only YES if the reasoning clearly identifies the correct mechanism
- Vague reasoning ("I fixed the bug") is NOT correct reasoning
- If uncertain, answer NO

# Output
Return EXACTLY one line:
<REASONING_CORRECT> ; <FAILURE_TYPE>

Where REASONING_CORRECT is YES or NO.

Examples:
YES ; HIDDEN_DEPENDENCY
NO ; INVARIANT_VIOLATION
YES ; TEMPORAL_ORDERING
NO ; UNKNOWN

Return ONLY this one line. No explanation.
```

### 4.8 Template Rules (Enforced)

1. **No logic in templates**: No `{% if %}`, no `{% for %}`, no `{% macro %}`. Templates are pure variable substitution with `{{ var }}` only. Enforced by a lint check during preflight validation:
   ```python
   def validate_template_no_logic(template_path: Path) -> None:
       content = template_path.read_text()
       logic_patterns = [r'{%\s*(if|for|macro|call|filter|set|block)', r'{%-?\s*(if|for|macro)']
       for pattern in logic_patterns:
           if re.search(pattern, content):
               raise TemplateError(
                   f"Template {template_path} contains forbidden logic: "
                   f"matched pattern '{pattern}'. Templates must be pure substitution."
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

    # 3. Validate no logic in templates
    for name, spec in TEMPLATE_REGISTRY.items():
        validate_template_no_logic(BASE_DIR / spec.path)

    # 4. Validate every condition's template references exist in registry
    #    (also validated during config load, but double-checked here)
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
            # NOTE (FIX 3): We do NOT check whether placeholders appear in rendered output.
            # A template may legitimately consume a variable without emitting it verbatim.
            # StrictUndefined + pre-render var set validation are sufficient.
        except Exception as e:
            raise TemplateError(
                f"Template '{name}' failed dry-render validation: {e}"
            ) from e

    # 6. Compute and cache all template hashes
    hashes = compute_all_template_hashes()
    _tpl_log.info(
        "PREFLIGHT: All %d templates validated OK. Hashes: %s",
        len(TEMPLATE_REGISTRY),
        {k: v[:12] for k, v in hashes.items()},
    )
```

### 4.10 Prompt Logging (FIX 6)

Every rendered prompt is logged to `run_prompts.jsonl` with FULL variable dictionary:

```python
def log_rendered_prompt(template_name: str, template_hash: str,
                        variables: dict, rendered: str) -> dict:
    """Build a prompt log record with full provenance.

    Returns the record dict. Caller writes it via RunLogger.
    """
    record = {
        "template_name": template_name,
        "template_hash": template_hash,
        "variables": variables,             # FIX 6: full variable dictionary, not just keys
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
# Added to each step's trajectory entry in retry_harness.py
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
# In the event dict passed to emit_event:
{
    # ... existing fields ...
    "step": ev.get("step", 0),
    "is_retry": ev.get("is_retry", False),
    "retry_reason": ev.get("retry_reason", ""),
    "prev_failure_type": ev.get("prev_failure_type"),
}
```

### 5.3 Modified Retry Loop (Pseudocode -- Exact Logic)

Changes to `retry_harness.py:run_retry_harness()`:

```python
def run_retry_harness(case, model, config: ExperimentConfig, ...):
    max_steps = config.retry.max_steps  # from config, not hardcoded
    condition = ...  # determined from use_contract/use_adaptive/use_alignment flags
    cond_cfg = config.conditions[condition]

    for step in range(max_steps):
        # --- RENDER PROMPT ---
        if step == 0:
            tpl_name = cond_cfg.template   # from config, not hardcoded
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

            tpl_name = cond_cfg.retry_template   # from config, not hardcoded
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

        # --- PARSE ---
        parsed = parse_structured_output(raw_output)
        # ... existing fallback logic ...

        # --- EVALUATE ---
        ev = _safe_evaluate(case, eval_parsed)

        # --- CLASSIFY (on failure) ---
        classification = None
        if not ev["pass"]:
            classification = classify_failure(error_obj, critique)

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

        _log_iteration(...)  # includes step, is_retry, retry_reason, prev_failure_type

        if ev["pass"]:
            break

        # --- NO BRANCHING -- linear only ---
        # construct retry input for next iteration
        # (critique, adaptive hints, etc. -- existing logic unchanged)
```

### 5.4 `_build_retry_reason` Helper

```python
def _build_retry_reason(prev_entry: dict) -> str:
    """Build a structured retry reason from the previous trajectory entry.

    Returns a human-readable string summarizing WHY this retry is happening.
    Used both in the retry prompt and in event logging.
    """
    parts = []

    # Failure type
    ft = prev_entry.get("failure_type")
    if ft:
        parts.append(f"failure_type={ft}")

    # Error category
    err = prev_entry.get("error", {})
    cat = err.get("category")
    if cat:
        parts.append(f"error_category={cat}")

    # Score
    score = prev_entry.get("score", 0)
    parts.append(f"prev_score={score:.2f}")

    # Test output summary (first 200 chars)
    test_out = prev_entry.get("test_output", "")
    if test_out:
        parts.append(f"test_summary={test_out[:200]}")

    return "; ".join(parts) if parts else "previous_attempt_failed"
```

### 5.5 Config-Driven Parameters

All retry parameters come from config:

| Parameter | Config Path | Current Hardcoded Value |
|---|---|---|
| `max_steps` | `config.retry.max_steps` | 5 |
| `timeout_total_seconds` | `config.execution.timeout_total_seconds` | 360 |
| `timeout_per_step_seconds` | `config.execution.timeout_per_step_seconds` | 60 |

The `retry_harness.py` module-level constants `MAX_ITERATION_SECONDS` and `MAX_TOTAL_SECONDS` become defaults used ONLY when config is not provided (backward compat for tests).

---

## 6. INTEGRATION FLOW (PART 4)

### 6.1 Startup Sequence

```
1. Parse CLI args
2. load_config("experiment.yaml")          -> ExperimentConfig (frozen)
3. preflight_validate_templates(config)     -> HARD ERROR if any template issue
4. preflight_verify_tests(cases)            -> HARD ERROR if any test missing
5. validate_run(cases, conditions)          -> HARD ERROR if incompatible pairs
6. log_resolved_config(config, run_dir)     -> config_resolved.yaml on disk
7. init_run_log(model, log_dir)             -> RunLogger active
8. Begin experiment loop
```

**Every step is fail-fast. No partial runs.**

### 6.2 Prompt Construction Flow

For each `(case, condition)` pair:

```
config.conditions[condition].template --------+
                                              v
                                    TEMPLATE_REGISTRY lookup
                                              |
                                              v
                                    spec.required_vars   (SOLE source of truth)
                                              |
                                 +------------+
                                 v            v
                        runtime variables   spec.required_vars
                                 |            |
                                 v            v
                            validate: provided == required (exact match)
                                      |
                                      v
                                if mismatch -> HARD ERROR
                                      |
                                      v
                            Jinja2.render(template, variables)
                            + compute_template_hash(spec)
                                      |
                                      v
                                 rendered prompt
                                      |
                                      v
                            log to run_prompts.jsonl
                            (with template_hash + full variables dict)
```

### 6.3 How Config Selects Templates

For **simple conditions** (baseline, diagnostic, guardrail, etc.):
1. Look up `config.conditions["baseline"].template` -> `"base"`
2. Render `"base"` template -> base prompt text
3. For nudge conditions: apply nudge operator (existing `nudges/router.py` logic) -> modified text

For **retry conditions** (retry_no_contract, retry_with_contract, etc.):
1. Step 0: `config.conditions["retry_no_contract"].template` -> `"base"`
2. Step 1+: `config.conditions["retry_no_contract"].retry_template` -> `"retry"`

For **multi-step conditions** (contract_gated):
1. Step 1 (elicit): `config.conditions["contract_gated"].template` -> `"contract_elicit"`
2. Step 2 (code gen): `config.conditions["contract_gated"].next_template` -> `"contract_code"`
3. Step 3 (retry): `config.conditions["contract_gated"].retry_template` -> `"contract_retry"`

**No hidden logic. Every mapping is visible in `experiment.yaml`.**

### 6.4 Variable Construction

Variables are constructed at the call site in `execution.py`, not in the template system:

```python
# For base template:
vars = {
    "task": case["task"],
    "code_files_block": _format_code_files(case["code_files_contents"]),
}

# For retry template:
vars = {
    "task": case["task"],
    "code_files_block": _format_code_files(case["code_files_contents"]),
    "previous_code": prev_entry["code"],
    "test_output": prev_entry["test_output"],
    "failure_reason": retry_reason,
    "step_number": str(step),
}
```

**There is no magic. Variables are built where data is available and passed explicitly.**

---

## 7. VALIDATION LOGIC (Comprehensive)

### 7.1 Config Validation Matrix

| Check | What | Error |
|---|---|---|
| Missing top-level key | `raw.keys() >= REQUIRED_TOP_KEYS` | `ConfigError("Missing required top-level keys: {missing}")` |
| Unknown top-level key | `raw.keys() <= REQUIRED_TOP_KEYS` | `ConfigError("Unknown top-level keys: {unknown}")` |
| Missing section key | e.g., `retry.enabled` absent | `ConfigError("retry.enabled is required")` |
| Wrong type | `retry.max_steps` is str | `ConfigError("retry.max_steps must be int, got str")` |
| Out of range | `retry.max_steps` = 0 | `ConfigError("retry.max_steps must be in [1, 20]")` |
| Invalid enum | `retry.strategy` = "tree" | `ConfigError("retry.strategy must be one of {'linear'}")` |
| Invalid condition name | `conditions.foo_bar` not in VALID_CONDITIONS | `ConfigError("conditions.foo_bar is not a valid condition")` |
| Missing condition template | `conditions.baseline` has no `template` key | `ConfigError("conditions.baseline.template is required")` |
| Unknown condition key | `conditions.baseline.bogus` | `ConfigError("Unknown keys in conditions.baseline: {'bogus'}")` |
| Template ref not in registry | `conditions.baseline.template = "nonexistent"` | `ConfigError("...not in TEMPLATE_REGISTRY")` |
| File missing | `execution.cases_file` doesn't exist | `ConfigError("...does not exist")` |

### 7.2 Template Validation Matrix

| Check | What | Error |
|---|---|---|
| Template not registered | `render("foo", ...)` | `TemplateNotFoundError` |
| Missing variable | `render("retry", {"task": ...})` (missing others) | `TemplateMissingVarError` |
| Extra variable | `render("base", {"task": ..., "extra": ...})` | `TemplateExtraVarError` |
| Template file missing | `TemplateSpec(path="nonexistent.jinja2")` | `TemplateNotFoundError` at preflight |
| Logic in template | `{% if x %}` in `.jinja2` file | `TemplateError` at preflight |
| Unregistered file | `templates/orphan.jinja2` exists | `TemplateError` at preflight |
| Jinja2 syntax error | Malformed `{{ }}` in template | `TemplateError` at preflight dry-render |
| Jinja2 StrictUndefined | Template references `{{ typo }}` not in required_vars | `jinja2.UndefinedError` at render time |

### 7.3 Runtime Validation

At every template render call:
1. Registry lookup (TemplateNotFoundError)
2. Exact variable set match (TemplateMissingVarError / TemplateExtraVarError)
3. Jinja2 StrictUndefined (backup safety net)

**Two independent safety nets ensure a missing variable NEVER passes silently.**

---

## 8. LOGGING SPEC

### 8.1 Per-Run Directory Contents

```
run_dir/
    config_resolved.yaml        # EXACT config used (written at start)
    metadata.json               # run metadata (model, trial, git hash, etc.)
    events.jsonl                # live metrics events
    run.jsonl                   # per-call eval records
    run_prompts.jsonl           # per-call prompts (with template provenance)
    run_responses.jsonl         # per-call raw model responses
```

### 8.2 `events.jsonl` Extended Schema

Each event line:

```json
{
  "model": "gpt-4o-mini",
  "trial": 1,
  "run_id": "a1b2c3d4",
  "case_id": "alias_config_a",
  "condition": "retry_no_contract",
  "timestamp": "2026-03-24T10:30:00.123",
  "pass": false,
  "score": 0.0,
  "step": 2,
  "is_retry": true,
  "retry_reason": "failure_type=HIDDEN_DEPENDENCY; error_category=logic; prev_score=0.00",
  "prev_failure_type": "HIDDEN_DEPENDENCY",
  "reasoning_correct": true,
  "code_correct": false,
  "failure_type": "HIDDEN_DEPENDENCY",
  "category": "leg",
  "num_attempts": 3,
  "elapsed_seconds": 4.2
}
```

### 8.3 `run_prompts.jsonl` Extended Schema (FIX 4 + FIX 6)

Each prompt record:

```json
{
  "run_id": "a1b2c3d4",
  "case_id": "alias_config_a",
  "condition": "retry_no_contract",
  "model": "gpt-4o-mini",
  "template_name": "retry",
  "template_hash": "a3f8c2e1b9d045...full_sha256...",
  "variables": {
    "task": "Refactor this code...",
    "code_files_block": "=== module.py ===\n...",
    "previous_code": "def fix(): ...",
    "test_output": "FAILED: invariant violated...",
    "failure_reason": "failure_type=HIDDEN_DEPENDENCY; ...",
    "step_number": "2"
  },
  "prompt": "... full rendered text ...",
  "step": 2,
  "is_retry": true
}
```

### 8.4 Debug Visibility

At `INFO` level, the template system logs:

```
TEMPLATE LOADED: templates/retry.jinja2 (hash=a3f8c2e1b9d0)
  REQUIRED VARS: ['code_files_block', 'failure_reason', 'previous_code', 'step_number', 'task', 'test_output']
  PROVIDED VARS: ['code_files_block', 'failure_reason', 'previous_code', 'step_number', 'task', 'test_output']
PROMPT RENDERED: template=retry hash=a3f8c2e1b9d0 vars=['code_files_block', 'failure_reason', 'previous_code', 'step_number', 'task', 'test_output'] len=3847
```

---

## 9. FAILURE MODES ELIMINATED

| Failure Mode | How Eliminated |
|---|---|
| Missing template variable -> silent default | `StrictUndefined` + pre-render set comparison = TWO independent checks. |
| Wrong template loaded -> unnoticed | Config explicitly names templates per condition. Registry maps names to files. Log shows template name + hash. |
| Variable name typo -> silent bug | `TemplateExtraVarError` catches extra vars (typos in caller). `TemplateMissingVarError` catches missing vars (typos in template). |
| Config drift between runs | `config_resolved.yaml` written to every run_dir at start. Frozen dataclass prevents runtime mutation. |
| Template file changed between runs | `template_hash` logged with every prompt. Comparing hashes across runs detects silent template changes (FIX 4). |
| Retry using wrong prompt | Template name + hash logged with every prompt. Step number in prompt. `is_retry=True/False` explicit in events. |
| Implicit retry (hidden retry count) | `step` field in every event. No retries outside the explicit `for step in range(max_steps)` loop. |
| Hardcoded magic numbers | `max_steps`, timeouts, strategy all from config. Config is logged. |
| Hardcoded condition-template mapping | Mapping lives in config YAML, not in Python code (FIX 2). |
| Duplicated variable requirements | `TemplateSpec.required_vars` is the SOLE source of truth (FIX 1). |
| Config depends on runtime code | Condition validation uses `constants.py`, a zero-dependency module (FIX 5). |
| Silent config loading failure | All config validation is fail-fast with specific error messages. |

---

## 10. FULL TEST PLAN

### 10.1 Template System Tests (`tests/test_templates.py`)

```python
# T1: Missing variable raises TemplateMissingVarError
def test_missing_variable_raises():
    with pytest.raises(TemplateMissingVarError, match="task"):
        render("base", {"code_files_block": "x"})

# T2: Extra variable raises TemplateExtraVarError
def test_extra_variable_raises():
    with pytest.raises(TemplateExtraVarError, match="extra"):
        render("base", {"task": "x", "code_files_block": "y", "extra": "z"})

# T3: Unknown template name raises TemplateNotFoundError
def test_unknown_template_raises():
    with pytest.raises(TemplateNotFoundError, match="nonexistent"):
        render("nonexistent", {})

# T4: Correct render produces exact expected output
def test_base_renders_correctly():
    result = render("base", {"task": "Fix the bug", "code_files_block": "def f(): pass"})
    assert "Fix the bug" in result
    assert "def f(): pass" in result

# T5: Empty variable value renders empty (not error)
def test_empty_string_variable():
    result = render("base", {"task": "", "code_files_block": ""})
    assert isinstance(result, str)

# T6: StrictUndefined catches template-level typos
def test_strict_undefined_catches_typo():
    from jinja2 import Environment, StrictUndefined
    env = Environment(undefined=StrictUndefined)
    template = env.from_string("{{ typo }}")
    with pytest.raises(Exception):
        template.render(task="x")

# T7: Retry template renders with all required vars
def test_retry_template_renders():
    result = render("retry", {
        "task": "Fix", "code_files_block": "code",
        "previous_code": "old", "test_output": "FAILED",
        "failure_reason": "logic error", "step_number": "1",
    })
    assert "step 1" in result
    assert "FAILED" in result

# T8: All registered templates can be dry-rendered
def test_all_templates_dry_render():
    for name, spec in TEMPLATE_REGISTRY.items():
        placeholders = {v: f"__{v}__" for v in spec.required_vars}
        result = render(name, placeholders)
        assert isinstance(result, str)
        assert len(result) > 0

# T9: Unregistered template file detected by preflight
def test_preflight_detects_unregistered_file(tmp_path):
    # Create a temp .jinja2 file not in registry -> preflight should fail
    ...

# T10: Logic in template detected by preflight
def test_preflight_detects_logic_in_template(tmp_path):
    # Create template with {% if %} -> preflight should fail
    ...

# T11: Template hash is deterministic
def test_template_hash_deterministic():
    spec = TEMPLATE_REGISTRY["base"]
    h1 = compute_template_hash(spec)
    clear_template_hash_cache()
    h2 = compute_template_hash(spec)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256

# T12: Template hash changes when file changes
def test_template_hash_changes_on_file_change(tmp_path):
    # Write a template, hash it, modify it, hash again -> different
    ...

# T13: render_with_metadata returns correct metadata
def test_render_with_metadata():
    rendered, meta = render_with_metadata("base", {"task": "x", "code_files_block": "y"})
    assert meta["template_name"] == "base"
    assert "template_hash" in meta
    assert len(meta["template_hash"]) == 64
    assert meta["variables"] == {"task": "x", "code_files_block": "y"}
    assert meta["rendered_length"] == len(rendered)
```

### 10.2 Config System Tests (`tests/test_config.py`)

```python
# C1: Missing required field raises ConfigError
def test_missing_experiment_name():
    raw = valid_config_dict()
    del raw["experiment"]["name"]
    with pytest.raises(ConfigError, match="name"):
        _validate_and_build(raw)

# C2: Wrong type raises ConfigError
def test_wrong_type_max_steps():
    raw = valid_config_dict()
    raw["retry"]["max_steps"] = "five"
    with pytest.raises(ConfigError, match="max_steps.*int.*str"):
        _validate_and_build(raw)

# C3: Unknown field raises ConfigError
def test_unknown_retry_field_rejected():
    raw = valid_config_dict()
    raw["retry"]["unknown_field"] = True
    with pytest.raises(ConfigError, match="Unknown keys"):
        _validate_and_build(raw)

# C4: Config is immutable after load
def test_config_immutable():
    config = load_config(test_config_path)
    with pytest.raises(AttributeError):  # FrozenInstanceError
        config.name = "modified"

# C5: Invalid condition name rejected
def test_invalid_condition_name():
    raw = valid_config_dict()
    raw["conditions"]["nonexistent_condition"] = {"template": "base"}
    with pytest.raises(ConfigError, match="not a valid condition"):
        _validate_and_build(raw)

# C6: Condition with missing template key rejected
def test_condition_missing_template():
    raw = valid_config_dict()
    raw["conditions"]["baseline"] = {}  # no template key
    with pytest.raises(ConfigError, match="template is required"):
        _validate_and_build(raw)

# C7: Condition with unknown key rejected
def test_condition_unknown_key():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["bogus"] = "value"
    with pytest.raises(ConfigError, match="Unknown keys"):
        _validate_and_build(raw)

# C8: Condition template ref not in registry rejected
def test_condition_template_not_in_registry():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["template"] = "nonexistent_template"
    with pytest.raises(ConfigError, match="not in TEMPLATE_REGISTRY"):
        _validate_and_build(raw)

# C9: max_steps out of range rejected
def test_max_steps_out_of_range():
    raw = valid_config_dict()
    raw["retry"]["max_steps"] = 0
    with pytest.raises(ConfigError, match="[1, 20]"):
        _validate_and_build(raw)

# C10: Valid config loads successfully
def test_valid_config_loads():
    config = load_config(test_config_path)
    assert config.name == "retry_ablation_v2"
    assert isinstance(config.models, tuple)
    assert isinstance(config.retry, RetryConfig)
    assert isinstance(config.conditions, dict)
    assert isinstance(config.conditions["baseline"], ConditionConfig)

# C11: config_resolved.yaml matches loaded config
def test_config_resolved_matches(tmp_path):
    config = load_config(test_config_path)
    log_resolved_config(config, tmp_path)
    resolved = yaml.safe_load((tmp_path / "config_resolved.yaml").read_text())
    assert resolved["retry"]["max_steps"] == config.retry.max_steps

# C12: Missing top-level section raises
def test_missing_top_level_section():
    raw = valid_config_dict()
    del raw["conditions"]
    with pytest.raises(ConfigError, match="Missing required top-level keys"):
        _validate_and_build(raw)

# C13: Unknown top-level section raises
def test_unknown_top_level_section():
    raw = valid_config_dict()
    raw["prompt_vars"] = {"required": ["task"]}  # removed section from v2
    with pytest.raises(ConfigError, match="Unknown top-level keys"):
        _validate_and_build(raw)

# C14: Empty conditions dict raises
def test_empty_conditions_rejected():
    raw = valid_config_dict()
    raw["conditions"] = {}
    with pytest.raises(ConfigError, match="non-empty"):
        _validate_and_build(raw)
```

### 10.3 Constants Tests (`tests/test_constants.py`)

```python
# K1: VALID_CONDITIONS is a frozenset
def test_valid_conditions_frozen():
    from constants import VALID_CONDITIONS
    assert isinstance(VALID_CONDITIONS, frozenset)

# K2: All labels are unique
def test_labels_unique():
    from constants import COND_LABELS
    assert len(set(COND_LABELS.values())) == len(COND_LABELS)

# K3: Every condition has a label
def test_every_condition_has_label():
    from constants import ALL_CONDITIONS, COND_LABELS
    for c in ALL_CONDITIONS:
        assert c in COND_LABELS, f"Condition {c} has no label"
```

### 10.4 Retry Trajectory Tests (`tests/test_retry_trajectory.py`)

```python
# R1: Step 0 has is_retry=False
def test_step_zero_not_retry():
    result = run_retry_harness(mock_case, "mock", config=mock_config, ...)
    trajectory = result[2]["trajectory"]
    assert trajectory[0]["step"] == 0
    assert trajectory[0]["is_retry"] is False
    assert trajectory[0]["retry_reason"] == ""
    assert trajectory[0]["prev_failure_type"] is None

# R2: Step 1+ has is_retry=True
def test_step_one_is_retry():
    result = run_retry_harness(always_fail_case, "mock", config=mock_config, ...)
    trajectory = result[2]["trajectory"]
    assert len(trajectory) >= 2
    assert trajectory[1]["step"] == 1
    assert trajectory[1]["is_retry"] is True
    assert trajectory[1]["retry_reason"] != ""

# R3: prev_failure_type propagated from previous step
def test_prev_failure_type_propagated():
    result = run_retry_harness(always_fail_case, "mock", config=mock_config, ...)
    trajectory = result[2]["trajectory"]
    if len(trajectory) >= 2:
        assert trajectory[1]["prev_failure_type"] is not None

# R4: Step increments correctly
def test_step_increments():
    result = run_retry_harness(always_fail_case, "mock", config=mock_config, ...)
    trajectory = result[2]["trajectory"]
    for i, entry in enumerate(trajectory):
        assert entry["step"] == i

# R5: max_steps from config is respected
def test_max_steps_from_config():
    config = make_config(max_steps=3)
    result = run_retry_harness(always_fail_case, "mock", config=config, ...)
    trajectory = result[2]["trajectory"]
    assert len(trajectory) <= 3

# R6: Retry uses correct template from config
def test_retry_uses_config_template(caplog):
    with caplog.at_level(logging.INFO, logger="t3.templates"):
        run_retry_harness(always_fail_case, "mock", config=mock_config, ...)
    assert "TEMPLATE LOADED" in caplog.text

# R7: retry_reason contains failure info
def test_retry_reason_has_content():
    result = run_retry_harness(always_fail_case, "mock", config=mock_config, ...)
    trajectory = result[2]["trajectory"]
    if len(trajectory) >= 2:
        reason = trajectory[1]["retry_reason"]
        assert "prev_score=" in reason

# R8: Events include step field
def test_events_include_step(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.touch()
    set_ablation_context(events_path, trial=1, run_id="test")
    run_retry_harness(mock_case, "mock", config=mock_config, ...)
    events = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    for e in events:
        assert "step" in e
        assert "is_retry" in e

# R9: Each trajectory entry has template_hash
def test_trajectory_has_template_hash():
    result = run_retry_harness(mock_case, "mock", config=mock_config, ...)
    trajectory = result[2]["trajectory"]
    for entry in trajectory:
        assert "template_hash" in entry
        assert len(entry["template_hash"]) == 64
```

### 10.5 Integration Tests (`tests/test_integration_config_template.py`)

```python
# I1: Config condition selects correct template from registry
def test_config_condition_selects_template():
    config = load_config(test_config_path)
    cond_cfg = config.conditions["baseline"]
    assert cond_cfg.template == "base"
    assert cond_cfg.template in TEMPLATE_REGISTRY

# I2: Config retry condition has retry_template
def test_config_retry_condition_has_retry_template():
    config = load_config(test_config_path)
    cond_cfg = config.conditions["retry_no_contract"]
    assert cond_cfg.retry_template == "retry"
    assert cond_cfg.retry_template in TEMPLATE_REGISTRY

# I3: Config contract condition has all three templates
def test_config_contract_has_all_templates():
    config = load_config(test_config_path)
    cond_cfg = config.conditions["contract_gated"]
    assert cond_cfg.template == "contract_elicit"
    assert cond_cfg.next_template == "contract_code"
    assert cond_cfg.retry_template == "contract_retry"

# I4: get_template_for_condition returns correct template per phase
def test_get_template_for_condition():
    config = load_config(test_config_path)
    assert get_template_for_condition(config, "retry_no_contract", "initial") == "base"
    assert get_template_for_condition(config, "retry_no_contract", "retry") == "retry"
    assert get_template_for_condition(config, "contract_gated", "next") == "contract_code"

# I5: get_template_for_condition raises on missing phase
def test_get_template_for_condition_missing_phase():
    config = load_config(test_config_path)
    with pytest.raises(ConfigError, match="no retry_template"):
        get_template_for_condition(config, "baseline", "retry")

# I6: Rendered prompt matches expected for known input
def test_rendered_prompt_matches_expected():
    result = render("base", {"task": "Fix the bug", "code_files_block": "code here"})
    assert result.strip() == "Fix the bug\n\ncode here"

# I7: Full pipeline: config -> template -> prompt
def test_full_pipeline(tmp_path):
    config = load_config(test_config_path)
    preflight_validate_templates(config)
    case = load_cases(cases_file=config.execution.cases_file)[0]
    tpl_name = config.conditions["baseline"].template
    rendered = render(tpl_name, {
        "task": case["task"],
        "code_files_block": _format_code_files(case["code_files_contents"]),
    })
    assert len(rendered) > 0
    assert "{{ " not in rendered  # no unrendered Jinja2 variables

# I8: End-to-end: config_resolved.yaml written and matches
def test_e2e_config_logged(tmp_path):
    config = load_config(test_config_path)
    log_resolved_config(config, tmp_path)
    written = yaml.safe_load((tmp_path / "config_resolved.yaml").read_text())
    assert written["retry"]["max_steps"] == config.retry.max_steps

# I9: Prompt log record contains full variables and hash
def test_prompt_log_record_complete():
    vars = {"task": "x", "code_files_block": "y"}
    rendered, meta = render_with_metadata("base", vars)
    record = log_rendered_prompt(
        meta["template_name"], meta["template_hash"],
        meta["variables"], rendered,
    )
    assert record["template_hash"] == meta["template_hash"]
    assert record["variables"] == vars
    assert record["rendered_prompt"] == rendered
```

---

## 11. BACKWARD COMPATIBILITY

### What Changes for Existing Code

1. **`runner.py`**: Imports `ALL_CONDITIONS`, `VALID_CONDITIONS`, `COND_LABELS` from `constants.py` instead of defining them locally. Gains `--config` argument. Legacy mode (no `--run-dir`) continues to work without a config file.

2. **`execution.py:build_prompt()`**: Gains an optional `use_templates: bool = False` parameter. When `True`, routes through `templates.render()` using config. When `False` (default), uses existing f-string path.

3. **`retry_harness.py:run_retry_harness()`**: Gains optional `config: ExperimentConfig | None = None`. When `None`, uses existing hardcoded defaults. When provided, reads templates and max_steps from config.

4. **All existing 68+ retry harness tests**: Continue to pass because `config=None` triggers existing defaults.

5. **Nudge-based conditions**: Unchanged. They post-process the base template output, not the template system directly.

### Migration Strategy

Phase 1: Ship `constants.py`, `config.py`, `templates.py`, all `.jinja2` files, and tests. `use_templates=False` default. Existing behavior unchanged.
Phase 2: Flip `use_templates=True` in ablation mode only. Verify all ablation runs match.
Phase 3: Remove legacy f-string paths once validated.
