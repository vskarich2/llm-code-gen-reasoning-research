# DESIGN PLAN: Retry + Trajectory, Config System, Templating System

**Version:** v1
**Date:** 2026-03-24
**Status:** Design complete, pending implementation
**Depends on:** retry_harness.py (implemented), runner.py, execution.py, evaluator.py, prompts.py

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
| `config.py` | Config loader, validator, frozen dataclass |
| `templates.py` | Template registry, Jinja2 renderer, validation |
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
| `retry_harness.py` | Add `step`, `is_retry`, `retry_reason`, `prev_failure_type` to trajectory events |
| `execution.py` | Route through template renderer; emit extended events |
| `runner.py` | Load config at startup; pass frozen config to subsystems |
| `live_metrics.py` | Accept extended event fields |
| `ablation_config.yaml` -> `experiment.yaml` | Replaced with strict schema |

---

## 2. CONFIG SYSTEM (PART 2 -- Designed First Because Everything Depends On It)

### 2.1 Schema Definition

File: `experiment.yaml`

```yaml
experiment:
  name: "retry_ablation_v2"          # str, required
  models:                             # list[str], required, min 1
    - "gpt-4o-mini"
    - "gpt-5-mini"
  conditions:                         # list[str], required, min 1
    - "baseline"
    - "retry_no_contract"
    - "retry_with_contract"
    - "retry_adaptive"

retry:
  enabled: true                       # bool, required
  max_steps: 5                        # int, required, range [1, 20]
  strategy: "linear"                  # str, required, one of: "linear"

templates:
  base: "templates/base.jinja2"       # str, required, must exist on disk
  retry: "templates/retry.jinja2"     # str, required, must exist on disk

prompt_vars:
  required:                           # list[str], required
    - "task"
    - "code_files_block"

execution:
  parallel: 1                         # int, required, range [1, 32]
  cases_file: "cases_v2.json"         # str, required, must exist on disk
  timeout_total_seconds: 360          # int, required
  timeout_per_step_seconds: 60        # int, required

logging:
  run_dir_pattern: "ablation_runs/run_{model}_t{trial}_{uuid}"  # str, required
  log_resolved_config: true           # bool, required
```

### 2.2 Python Schema (Frozen Dataclasses)

File: `config.py`

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class RetryConfig:
    enabled: bool
    max_steps: int
    strategy: str

@dataclass(frozen=True)
class TemplatesConfig:
    base: str
    retry: str

@dataclass(frozen=True)
class PromptVarsConfig:
    required: tuple[str, ...]   # tuple, not list, for immutability

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
    conditions: tuple[str, ...]
    retry: RetryConfig
    templates: TemplatesConfig
    prompt_vars: PromptVarsConfig
    execution: ExecutionConfig
    logging: LoggingConfig
```

### 2.3 Loader and Validator

```python
def load_config(path: Path) -> ExperimentConfig:
    """Load, validate, and freeze config. Raises on ANY error."""
```

**Validation steps (in order, all mandatory):**

1. **File exists**: `if not path.exists(): raise FileNotFoundError(...)`

2. **YAML parse**: `yaml.safe_load()` -- raises on invalid YAML

3. **Top-level keys check**:
   ```python
   REQUIRED_TOP_KEYS = {"experiment", "retry", "templates", "prompt_vars", "execution", "logging"}
   missing = REQUIRED_TOP_KEYS - raw.keys()
   if missing:
       raise ConfigError(f"Missing required top-level keys: {missing}")
   unknown = raw.keys() - REQUIRED_TOP_KEYS
   if unknown:
       raise ConfigError(f"Unknown top-level keys: {unknown}")
   ```

4. **Per-section validation** (example for `retry`):
   ```python
   RETRY_REQUIRED = {"enabled": bool, "max_steps": int, "strategy": str}
   RETRY_STRATEGY_VALUES = {"linear"}

   retry_raw = raw["retry"]
   for key, expected_type in RETRY_REQUIRED.items():
       if key not in retry_raw:
           raise ConfigError(f"retry.{key} is required")
       if not isinstance(retry_raw[key], expected_type):
           raise ConfigError(
               f"retry.{key} must be {expected_type.__name__}, "
               f"got {type(retry_raw[key]).__name__}"
           )
   unknown_retry = retry_raw.keys() - RETRY_REQUIRED.keys()
   if unknown_retry:
       raise ConfigError(f"Unknown keys in retry: {unknown_retry}")
   if retry_raw["strategy"] not in RETRY_STRATEGY_VALUES:
       raise ConfigError(f"retry.strategy must be one of {RETRY_STRATEGY_VALUES}")
   if not (1 <= retry_raw["max_steps"] <= 20):
       raise ConfigError("retry.max_steps must be in [1, 20]")
   ```

5. **Condition validation**: Every condition in `experiment.conditions` must exist in `runner.VALID_CONDITIONS`. Checked by:
   ```python
   from runner import VALID_CONDITIONS
   invalid = set(cfg.conditions) - VALID_CONDITIONS
   if invalid:
       raise ConfigError(f"Invalid conditions: {invalid}")
   ```

6. **File existence validation**: `templates.base`, `templates.retry`, `execution.cases_file` must exist on disk relative to project root.
   ```python
   for label, rel_path in [("templates.base", ...), ("templates.retry", ...), ...]:
       full = BASE_DIR / rel_path
       if not full.exists():
           raise ConfigError(f"{label} points to {full} which does not exist")
   ```

7. **Freeze**: Construct the `ExperimentConfig` frozen dataclass. Lists become tuples.

8. **Mutation test**: After construction, attempt `config.name = "x"` -- must raise `FrozenInstanceError`. This is guaranteed by `frozen=True` but the test explicitly verifies it.

### 2.4 Config Logging

At the start of every run, the exact config is serialized to disk:

```python
def log_resolved_config(config: ExperimentConfig, run_dir: Path) -> Path:
    """Write config_resolved.yaml to run_dir. Returns path written."""
    import dataclasses, yaml
    d = dataclasses.asdict(config)
    # Convert tuples back to lists for YAML readability
    out_path = run_dir / "config_resolved.yaml"
    with open(out_path, "w") as f:
        yaml.dump(d, f, default_flow_style=False)
    return out_path
```

**Invariant**: `config_resolved.yaml` in every run directory is the EXACT config that produced that run's data. No exceptions.

### 2.5 Integration Point

In `runner.py:main()` and `runner.py:_run_ablation_mode()`:

```python
# At top of main(), BEFORE any other work:
config = load_config(BASE_DIR / args.config)  # new --config arg, default "experiment.yaml"
# All downstream code receives `config`, never reads raw YAML again
```

The config object is passed explicitly -- never stored in module-level globals. Functions that need it receive it as an argument.

---

## 3. TEMPLATE SYSTEM (PART 3)

### 3.1 Template Registry

File: `templates.py`

```python
from dataclasses import dataclass
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

@dataclass(frozen=True)
class TemplateSpec:
    name: str
    path: str                        # relative to templates/ dir
    required_vars: frozenset[str]    # exact set of required variables

# Central registry -- every template the system uses MUST be registered here.
# Adding a template without registering it is a bug.
TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {}

def register(spec: TemplateSpec) -> None:
    if spec.name in TEMPLATE_REGISTRY:
        raise RuntimeError(f"Duplicate template registration: {spec.name}")
    TEMPLATE_REGISTRY[spec.name] = spec
```

### 3.2 Registered Templates

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

### 3.3 Jinja2 Environment

```python
import logging
_tpl_log = logging.getLogger("t3.templates")

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

### 3.4 Render Function (The Critical Path)

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

    # Step 3: Log what we're doing
    _tpl_log.info(
        "TEMPLATE LOADED: %s\n  REQUIRED VARS: %s\n  PROVIDED VARS: %s",
        spec.path, sorted(spec.required_vars), sorted(provided)
    )

    # Step 4: Render (StrictUndefined is the second safety net)
    env = _get_env()
    template = env.get_template(spec.path.replace("templates/", ""))
    rendered = template.render(**variables)

    return rendered
```

### 3.5 Custom Exceptions

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

### 3.6 Template File Contents

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

### 3.7 Template Rules (Enforced)

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

### 3.8 Preflight Template Validation

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

    # 4. Validate config template paths match registry
    config_templates = {
        "base": config.templates.base,
        "retry": config.templates.retry,
    }
    for label, path in config_templates.items():
        found = False
        for spec in TEMPLATE_REGISTRY.values():
            if spec.path == path:
                found = True
                break
        if not found:
            raise ConfigError(
                f"Config templates.{label} = '{path}' does not match any registered template"
            )

    # 5. Dry-render all templates with placeholder values to verify Jinja2 syntax
    env = _get_env()
    for name, spec in TEMPLATE_REGISTRY.items():
        try:
            template = env.get_template(spec.path.replace("templates/", ""))
            placeholders = {var: f"__PLACEHOLDER_{var}__" for var in spec.required_vars}
            rendered = template.render(**placeholders)
            # Verify all placeholders appear in output
            for var in spec.required_vars:
                if f"__PLACEHOLDER_{var}__" not in rendered:
                    raise TemplateError(
                        f"Template '{name}' does not use declared required var '{var}'"
                    )
        except Exception as e:
            raise TemplateError(
                f"Template '{name}' failed dry-render validation: {e}"
            ) from e

    _tpl_log.info("PREFLIGHT: All %d templates validated OK", len(TEMPLATE_REGISTRY))
```

### 3.9 Prompt Logging

Every rendered prompt is logged to `run_prompts.jsonl`:

```python
def log_rendered_prompt(template_name: str, variables: dict, rendered: str,
                        run_logger) -> None:
    """Log a rendered prompt with full provenance."""
    record = {
        "template_name": template_name,
        "variables_used": sorted(variables.keys()),
        "rendered_prompt": rendered,
        "rendered_length": len(rendered),
    }
    _tpl_log.info(
        "PROMPT RENDERED: template=%s vars=%s len=%d",
        template_name, sorted(variables.keys()), len(rendered)
    )
    return record  # caller includes in write_log
```

---

## 4. RETRY + TRAJECTORY SYSTEM (PART 1)

### 4.1 Extended Event Schema

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

### 4.2 Extended Event Emission

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

### 4.3 Modified Retry Loop (Pseudocode -- Exact Logic)

Changes to `retry_harness.py:run_retry_harness()`:

```python
def run_retry_harness(case, model, config: ExperimentConfig, ...):
    max_steps = config.retry.max_steps  # from config, not hardcoded

    for step in range(max_steps):
        # --- RENDER PROMPT ---
        if step == 0:
            prompt = render("base", {
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

            prompt = render("retry", {
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
        }
        trajectory.append(step_entry)

        _log_iteration(...)  # includes step, is_retry, retry_reason, prev_failure_type

        if ev["pass"]:
            break

        # --- NO BRANCHING -- linear only ---
        # construct retry input for next iteration
        # (critique, adaptive hints, etc. -- existing logic unchanged)
```

### 4.4 `_build_retry_reason` Helper

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

### 4.5 Config-Driven Parameters

All retry parameters come from config:

| Parameter | Config Path | Current Hardcoded Value |
|---|---|---|
| `max_steps` | `config.retry.max_steps` | 5 |
| `timeout_total_seconds` | `config.execution.timeout_total_seconds` | 360 |
| `timeout_per_step_seconds` | `config.execution.timeout_per_step_seconds` | 60 |

The `retry_harness.py` module-level constants `MAX_ITERATION_SECONDS` and `MAX_TOTAL_SECONDS` become defaults used ONLY when config is not provided (backward compat for tests).

---

## 5. INTEGRATION FLOW (PART 4)

### 5.1 Startup Sequence

```
1. Parse CLI args
2. load_config("experiment.yaml")        -> ExperimentConfig (frozen)
3. preflight_validate_templates(config)   -> HARD ERROR if any template issue
4. preflight_verify_tests(cases)          -> HARD ERROR if any test missing
5. validate_run(cases, conditions)        -> HARD ERROR if incompatible pairs
6. log_resolved_config(config, run_dir)   -> config_resolved.yaml on disk
7. init_run_log(model, log_dir)           -> RunLogger active
8. Begin experiment loop
```

**Every step is fail-fast. No partial runs.**

### 5.2 Prompt Construction Flow

For each `(case, condition)` pair:

```
config.templates.base ----------------------------------------+
                                                              v
                                                    TEMPLATE_REGISTRY lookup
                                                              |
                                                              v
                                                    spec.required_vars
                                                              |
                                                 +------------+
                                                 v            v
                                        runtime variables   spec.required_vars
                                                 |            |
                                                 v            v
                                            validate: provided = required (exact)
                                                      |
                                                      v
                                                if mismatch -> HARD ERROR
                                                      |
                                                      v
                                            Jinja2.render(template, variables)
                                                      |
                                                      v
                                                 rendered prompt
                                                      |
                                                      v
                                            log to run_prompts.jsonl
```

### 5.3 How Config Selects Templates

The config contains template paths. The runner maps conditions to template names:

```python
# In execution.py -- the condition->template mapping is EXPLICIT, not dynamic

CONDITION_TEMPLATE_MAP = {
    "baseline": "base",
    "repair_loop": "base",         # initial prompt; feedback uses "repair_feedback"
    "retry_no_contract": "base",   # initial; retries use "retry"
    "retry_with_contract": "base", # initial; retries use "retry"
    "retry_adaptive": "base",      # initial; retries use "retry"
    "retry_alignment": "base",     # initial; retries use "retry"
    "contract_gated": "contract_elicit",  # step 1; step 2 uses "contract_code"
    # ... nudge conditions use nudge operators which post-process the base template output
}
```

For nudge-based conditions (diagnostic, guardrail, etc.), the flow is:
1. Render `"base"` template -> base prompt text
2. Apply nudge operator (existing `nudges/router.py` logic) -> modified prompt text

This preserves the existing nudge system without requiring nudge-per-template files.

### 5.4 Variable Construction

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

## 6. VALIDATION LOGIC (Comprehensive)

### 6.1 Config Validation Matrix

| Check | What | Error |
|---|---|---|
| Missing top-level key | `raw.keys() >= REQUIRED_TOP_KEYS` | `ConfigError("Missing required top-level keys: {missing}")` |
| Unknown top-level key | `raw.keys() <= REQUIRED_TOP_KEYS` | `ConfigError("Unknown top-level keys: {unknown}")` |
| Missing section key | e.g., `retry.enabled` absent | `ConfigError("retry.enabled is required")` |
| Wrong type | `retry.max_steps` is str | `ConfigError("retry.max_steps must be int, got str")` |
| Out of range | `retry.max_steps` = 0 | `ConfigError("retry.max_steps must be in [1, 20]")` |
| Invalid enum | `retry.strategy` = "tree" | `ConfigError("retry.strategy must be one of {'linear'}")` |
| Invalid condition | `conditions` contains "foo" | `ConfigError("Invalid conditions: {'foo'}")` |
| File missing | `templates.base` = "templates/missing.jinja2" | `ConfigError("...does not exist")` |
| Unknown section key | `retry.foo` = 1 | `ConfigError("Unknown keys in retry: {'foo'}")` |

### 6.2 Template Validation Matrix

| Check | What | Error |
|---|---|---|
| Template not registered | `render("foo", ...)` | `TemplateNotFoundError` |
| Missing variable | `render("retry", {"task": ...})` (missing others) | `TemplateMissingVarError` |
| Extra variable | `render("base", {"task": ..., "extra": ...})` | `TemplateExtraVarError` |
| Template file missing | `TemplateSpec(path="nonexistent.jinja2")` | `TemplateNotFoundError` at preflight |
| Logic in template | `{% if x %}` in `.jinja2` file | `TemplateError` at preflight |
| Unregistered file | `templates/orphan.jinja2` exists | `TemplateError` at preflight |
| Var declared but unused | Template doesn't use `{{ var }}` | `TemplateError` at preflight dry-render |
| Jinja2 StrictUndefined | Template references `{{ typo }}` | `jinja2.UndefinedError` at render time |

### 6.3 Runtime Validation

At every template render call:
1. Registry lookup (TemplateNotFoundError)
2. Exact variable set match (TemplateMissingVarError / TemplateExtraVarError)
3. Jinja2 StrictUndefined (backup safety net)

**Two independent safety nets ensure a missing variable NEVER passes silently.**

---

## 7. LOGGING SPEC

### 7.1 Per-Run Directory Contents

```
run_dir/
    config_resolved.yaml        # EXACT config used (written at start)
    metadata.json               # run metadata (model, trial, git hash, etc.)
    events.jsonl                # live metrics events
    run.jsonl                   # per-call eval records
    run_prompts.jsonl           # per-call prompts (with template provenance)
    run_responses.jsonl         # per-call raw model responses
```

### 7.2 `events.jsonl` Extended Schema

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

### 7.3 `run_prompts.jsonl` Extended Schema

Each prompt record:

```json
{
  "run_id": "a1b2c3d4",
  "case_id": "alias_config_a",
  "condition": "retry_no_contract",
  "model": "gpt-4o-mini",
  "template_name": "retry",
  "variables_used": ["task", "code_files_block", "previous_code", "test_output", "failure_reason", "step_number"],
  "prompt": "... full rendered text ...",
  "step": 2,
  "is_retry": true
}
```

### 7.4 Debug Visibility

At `INFO` level, the template system logs:

```
TEMPLATE LOADED: retry.jinja2
  REQUIRED VARS: ['code_files_block', 'failure_reason', 'previous_code', 'step_number', 'task', 'test_output']
  PROVIDED VARS: ['code_files_block', 'failure_reason', 'previous_code', 'step_number', 'task', 'test_output']
PROMPT RENDERED: template=retry vars=['code_files_block', 'failure_reason', 'previous_code', 'step_number', 'task', 'test_output'] len=3847
```

---

## 8. FAILURE MODES ELIMINATED

| Failure Mode | How Eliminated |
|---|---|
| Missing template variable -> silent default | `StrictUndefined` + pre-render set comparison = TWO independent checks. Both must fail for a bug. |
| Wrong template loaded -> unnoticed | Config explicitly names templates. Registry maps names to files. Log shows which template rendered. |
| Variable name typo -> silent bug | `TemplateExtraVarError` catches extra vars (typos in caller). `TemplateMissingVarError` catches missing vars (typos in template). |
| Config drift between runs | `config_resolved.yaml` written to every run_dir at start. Frozen dataclass prevents runtime mutation. |
| Retry using wrong prompt | Template name logged with every prompt. Step number in prompt. `is_retry=True/False` explicit in events. |
| Implicit retry (hidden retry count) | `step` field in every event. No retries happen outside the explicit `for step in range(max_steps)` loop. |
| Hardcoded magic numbers | `max_steps`, timeouts, strategy all from config. Config is logged. |
| Silent config loading failure | All config validation is fail-fast with specific error messages. No `try/except` around validation. |

---

## 9. FULL TEST PLAN

### 9.1 Template System Tests (`tests/test_templates.py`)

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
    # Manually create a bad template to verify StrictUndefined works
    # (This tests the Jinja2 safety net, not our pre-render check)
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
        for v in spec.required_vars:
            assert f"__{v}__" in result, f"Template {name} did not use var {v}"

# T9: Unregistered template file detected by preflight
def test_preflight_detects_unregistered_file(tmp_path):
    # Create a temp .jinja2 file not in registry -> preflight should fail
    ...

# T10: Logic in template detected by preflight
def test_preflight_detects_logic_in_template(tmp_path):
    # Create template with {% if %} -> preflight should fail
    ...
```

### 9.2 Config System Tests (`tests/test_config.py`)

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
def test_unknown_field_rejected():
    raw = valid_config_dict()
    raw["retry"]["unknown_field"] = True
    with pytest.raises(ConfigError, match="Unknown keys"):
        _validate_and_build(raw)

# C4: Config is immutable after load
def test_config_immutable():
    config = load_config(test_config_path)
    with pytest.raises(AttributeError):  # FrozenInstanceError
        config.name = "modified"

# C5: Invalid condition rejected
def test_invalid_condition():
    raw = valid_config_dict()
    raw["experiment"]["conditions"] = ["baseline", "nonexistent"]
    with pytest.raises(ConfigError, match="nonexistent"):
        _validate_and_build(raw)

# C6: Template file that doesn't exist rejected
def test_missing_template_file():
    raw = valid_config_dict()
    raw["templates"]["base"] = "templates/missing.jinja2"
    with pytest.raises(ConfigError, match="does not exist"):
        _validate_and_build(raw)

# C7: max_steps out of range rejected
def test_max_steps_out_of_range():
    raw = valid_config_dict()
    raw["retry"]["max_steps"] = 0
    with pytest.raises(ConfigError, match="[1, 20]"):
        _validate_and_build(raw)

# C8: Valid config loads successfully
def test_valid_config_loads():
    config = load_config(test_config_path)
    assert config.name == "retry_ablation_v2"
    assert isinstance(config.models, tuple)
    assert isinstance(config.retry, RetryConfig)

# C9: config_resolved.yaml matches loaded config
def test_config_resolved_matches(tmp_path):
    config = load_config(test_config_path)
    log_resolved_config(config, tmp_path)
    resolved = yaml.safe_load((tmp_path / "config_resolved.yaml").read_text())
    assert resolved["experiment"]["name"] == config.name

# C10: Missing top-level section raises
def test_missing_top_level_section():
    raw = valid_config_dict()
    del raw["templates"]
    with pytest.raises(ConfigError, match="Missing required top-level keys"):
        _validate_and_build(raw)
```

### 9.3 Retry Trajectory Tests (`tests/test_retry_trajectory.py`)

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
    # Mock case that always fails -> forces retry
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

# R6: Retry uses correct template
def test_retry_uses_retry_template(caplog):
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
    # Run with ablation context set -> check events.jsonl
    events_path = tmp_path / "events.jsonl"
    events_path.touch()
    set_ablation_context(events_path, trial=1, run_id="test")
    run_retry_harness(mock_case, "mock", config=mock_config, ...)
    events = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    for e in events:
        assert "step" in e
        assert "is_retry" in e
```

### 9.4 Integration Tests (`tests/test_integration_config_template.py`)

```python
# I1: Config selects correct template
def test_config_template_selection():
    config = load_config(test_config_path)
    spec = TEMPLATE_REGISTRY["base"]
    assert spec.path == config.templates.base

# I2: Template receives correct variables from build_prompt
def test_build_prompt_provides_correct_vars():
    with patch("templates.render") as mock_render:
        mock_render.return_value = "rendered"
        build_prompt(mock_case, "baseline")
        mock_render.assert_called_once_with("base", {
            "task": mock_case["task"],
            "code_files_block": ANY,
        })

# I3: Rendered prompt matches expected for known input
def test_rendered_prompt_matches_expected():
    result = render("base", {"task": "Fix the bug", "code_files_block": "code here"})
    assert result.strip() == "Fix the bug\n\ncode here"

# I4: Full pipeline: config -> template -> prompt -> model call
def test_full_pipeline(tmp_path):
    config = load_config(test_config_path)
    preflight_validate_templates(config)
    case = load_cases(cases_file=config.execution.cases_file)[0]
    prompt, op = build_prompt(case, "baseline")
    assert len(prompt) > 0
    assert "{{ " not in prompt  # no unrendered Jinja2 variables

# I5: End-to-end: config_resolved.yaml written and matches
def test_e2e_config_logged(tmp_path):
    config = load_config(test_config_path)
    log_resolved_config(config, tmp_path)
    written = yaml.safe_load((tmp_path / "config_resolved.yaml").read_text())
    assert written["retry"]["max_steps"] == config.retry.max_steps

# I6: Template change without registry update caught
def test_template_file_change_caught():
    # If someone adds a .jinja2 file without registering it,
    # preflight_validate_templates raises
    ...
```

---

## 10. BACKWARD COMPATIBILITY

### What Changes for Existing Code

1. **`runner.py`**: Gains `--config` argument. Without it, falls back to default `experiment.yaml`. Legacy mode (no `--run-dir`) continues to work without a config file -- the config system is opt-in for ablation mode.

2. **`execution.py:build_prompt()`**: Gains an optional `use_templates: bool = False` parameter. When `True`, routes through `templates.render()`. When `False` (default), uses existing f-string path. This allows incremental migration.

3. **`retry_harness.py:run_retry_harness()`**: Gains optional `config: ExperimentConfig | None = None`. When `None`, uses existing hardcoded defaults. When provided, uses config values. Existing callers are unchanged.

4. **All existing 68+ retry harness tests**: Continue to pass because `config=None` triggers existing defaults.

5. **Nudge-based conditions**: Unchanged. They post-process the base template output, not the template system directly.

### Migration Strategy

Phase 1: Ship all new code with `use_templates=False` default. Existing behavior unchanged.
Phase 2: Flip `use_templates=True` in ablation mode only. Verify all ablation runs match.
Phase 3: Remove legacy f-string paths once validated.
