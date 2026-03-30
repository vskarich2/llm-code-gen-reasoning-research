# Unified YAML Configuration System — Design Document (v2)

**Date:** 2026-03-27
**Supersedes:** UNIFIED_YAML_CONFIG_SYSTEM_v1.md
**Status:** Partially implemented. `experiment_config.py`, `templates.py`, and `templates/` exist.

**v1 → v2 changes:**
- Conditions use `template`, `retry_template`, `next_template` (not flat `prompt_template`)
- Template system (`templates.py`) with registry, hashing, strict var validation is implemented
- Condition categories (SIMPLE, RETRY, MULTISTEP from `constants.py`) define structural template requirements
- `preflight_validate_templates()` validates config → template cross-references at startup
- Jinja2 templates with `required_vars` frozensets replace inline prompt strings
- `render_with_metadata()` returns template hash + provenance for logging

---

## 1. Design Rationale

Unchanged from v1. The config consolidates all experimental parameters into one YAML file.

Additionally, the template system (`templates.py`) is now the canonical prompt rendering layer:
- Templates registered in `TEMPLATE_REGISTRY` with `TemplateSpec(name, path, required_vars)`
- `render(template_name, variables)` validates required/extra vars before Jinja2 render
- `init_template_hashes()` computes SHA-256 hashes at startup (immutable)
- `preflight_validate_templates(config)` checks all condition→template references at startup

The config must integrate with this system. Conditions reference template names by string; the template registry resolves and validates them.

---

## 2. Full YAML Schema (Complete Example)

```yaml
# ============================================================
# T3 Ablation Experiment Configuration
# ============================================================

experiment:
  name: "retry_ablation_v3"
  description: "Retry-based interventions with LEG measurement on v2 cases"
  tags: ["ablation", "retry", "LEG", "v3_pipeline"]
  seed: 42

run:
  trial: 1
  run_id: "retry_v3_001"
  run_dir: "logs/retry_v3_run"

models:
  generation:
    - name: "gpt-4.1-nano"
      temperature: 0.0
      max_tokens: 4096
      top_p: 1.0

    - name: "gpt-4o-mini"
      temperature: 0.0
      max_tokens: 4096
      top_p: 1.0

  evaluator:
    name: "gpt-5.4-mini"
    temperature: 0.0
    max_tokens: 1024
    max_task_chars: 800
    max_code_chars: 2000
    max_reasoning_chars: 1000

  failure_classifier:
    name: null  # defaults to evaluator.name

# ------------------------------------------------------------
# CONDITIONS
# ------------------------------------------------------------
# Each condition defines a complete experimental treatment.
#
# Template fields:
#   template       — used for the initial prompt (REQUIRED for all conditions)
#   retry_template — used for retry prompts (REQUIRED for RETRY_CONDITIONS)
#   next_template  — used for next-step prompts (REQUIRED for MULTISTEP_CONDITIONS)
#
# Template names must match entries in TEMPLATE_REGISTRY (templates.py).
# Structural rules enforced by constants.py categories:
#   SIMPLE_CONDITIONS:    template only, no retry_template, no next_template
#   RETRY_CONDITIONS:     template + retry_template, no next_template
#   MULTISTEP_CONDITIONS: template + retry_template + next_template

conditions:
  baseline:
    template: "base"
    retry:
      enabled: false

  diagnostic:
    template: "base"
    retry:
      enabled: false

  guardrail:
    template: "base"
    retry:
      enabled: false

  guardrail_strict:
    template: "base"
    retry:
      enabled: false

  retry_no_contract:
    template: "base"
    retry_template: "retry"
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: false
        include_previous_code: true

  retry_with_contract:
    template: "base"
    retry_template: "retry"
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: false
        include_previous_code: true
    contract:
      enabled: true

  retry_alignment:
    template: "base"
    retry_template: "retry"
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: true
        include_previous_code: true
    contract:
      enabled: true
    critique:
      enabled: true

  retry_adaptive:
    template: "base"
    retry_template: "retry"
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: true
        include_previous_code: true
      stopping:
        stop_on_stagnation: true
        stagnation_window: 3

  contract_gated:
    template: "contract_elicit"
    next_template: "contract_code"
    retry_template: "contract_retry"
    contract:
      enabled: true

  repair_loop:
    template: "base"
    retry_template: "repair_feedback"
    retry:
      enabled: true
      max_attempts: 2

  leg_reduction:
    template: "base"
    retry:
      enabled: false

# ------------------------------------------------------------
# CASES
# ------------------------------------------------------------
cases:
  source: "cases_v2.json"
  mode: "all"
  max_cases: 0

# ------------------------------------------------------------
# RETRY DEFAULTS
# ------------------------------------------------------------
retry_defaults:
  max_attempts: 5
  similarity_threshold: 0.95
  score_epsilon: 0.05
  persistence_escalation_count: 2
  max_iteration_seconds: 60
  max_total_seconds: 360
  feedback:
    include_test_output: true
    include_critique: false
    include_previous_code: true
  stopping:
    stop_on_pass: true
    stop_on_stagnation: false

# ------------------------------------------------------------
# EVALUATION
# ------------------------------------------------------------
evaluation:
  execution_mode: "in_process"
  subprocess_timeout: 30
  leg:
    enabled: true
  failure_classification:
    enabled: true
  alignment:
    enabled: true

# ------------------------------------------------------------
# EXECUTION
# ------------------------------------------------------------
execution:
  num_workers: 1
  token_budgets:
    "gpt-4.1-nano": 12000
    "gpt-4o-mini": 12000
    "gpt-5-mini": 16000
    "gpt-5.4-mini": 16000
    default: 10000
  v3_pipeline:
    import_summary: false
    file_ordering: "dependency"

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
logging:
  level: "INFO"
  output_dir: "logs/"
  store:
    raw_prompts: true
    raw_outputs: true
    generated_code: true
    execution_traces: true
  redis:
    enabled: false
    url: "redis://localhost:6379/0"
    stream_maxlen: 100000

trials: 1
```

---

## 3. Condition Config Model (REVISED)

### 3.1 ConditionConfig Dataclass

```python
@dataclass
class ConditionConfig:
    template: str                        # initial prompt template (REQUIRED)
    retry_template: str | None = None    # retry prompt template (REQUIRED for RETRY_CONDITIONS)
    next_template: str | None = None     # next-step template (REQUIRED for MULTISTEP_CONDITIONS)
    retry: RetryConfig = field(default_factory=RetryConfig)
    contract_enabled: bool = False
    contract_injection_point: str = "before_code"
    critique_enabled: bool = False
    critique_model: str | None = None
```

### 3.2 Template Field Rules

| Condition category | `template` | `retry_template` | `next_template` |
|-------------------|-----------|------------------|-----------------|
| `SIMPLE_CONDITIONS` | REQUIRED | FORBIDDEN (must be None) | FORBIDDEN (must be None) |
| `RETRY_CONDITIONS` | REQUIRED | REQUIRED | FORBIDDEN (must be None) |
| `MULTISTEP_CONDITIONS` | REQUIRED | REQUIRED | REQUIRED |

These rules are enforced at config validation time. Violation is a hard error.

### 3.3 Template Name → Registry Binding

Every template name referenced in a condition MUST exist in `TEMPLATE_REGISTRY` (defined in `templates.py`).

Current registered templates:
| Registry name | File | Required vars |
|--------------|------|---------------|
| `base` | `templates/base.jinja2` | `task`, `code_files_block` |
| `retry` | `templates/retry.jinja2` | `task`, `code_files_block`, `previous_code`, `test_output`, `failure_reason`, `step_number` |
| `repair_feedback` | `templates/repair_feedback.jinja2` | `task`, `code_files_block`, `error_reasons` |
| `contract_elicit` | `templates/contract_elicit.jinja2` | `task`, `code_files_block`, `contract_schema` |
| `contract_code` | `templates/contract_code.jinja2` | `task`, `code_files_block`, `contract_json` |
| `contract_retry` | `templates/contract_retry.jinja2` | `task`, `code_files_block`, `contract_json`, `violations_text` |
| `classify` | `templates/classify.jinja2` | `failure_types`, `task`, `code`, `reasoning` |

### 3.4 Template Resolution at Runtime

```python
def get_template_for_condition(config, condition_name: str, phase: str) -> str:
    """Return the template name for a condition at a given execution phase.

    phase: "initial" | "retry" | "next"
    Raises ConfigError if the requested phase has no template.
    """
    cond = config.conditions[condition_name]
    if phase == "initial":
        return cond.template
    elif phase == "retry":
        if cond.retry_template is None:
            raise ConfigError(f"Condition '{condition_name}' has no retry_template")
        return cond.retry_template
    elif phase == "next":
        if cond.next_template is None:
            raise ConfigError(f"Condition '{condition_name}' has no next_template")
        return cond.next_template
```

### 3.5 Rendering a Prompt

```python
from templates import render_with_metadata

# At the point where a prompt is needed:
template_name = get_template_for_condition(config, condition, phase)
variables = build_template_variables(case, condition, state)  # assembles task, code_files_block, etc.
rendered_prompt, prompt_metadata = render_with_metadata(template_name, variables)

# prompt_metadata contains:
#   template_name, template_hash, variables, rendered_length
# This is logged alongside the LLM call for full reproducibility.
```

---

## 4. Validation Layer (REVISED)

### 4.1 Config Validation (at YAML load time)

Unchanged from v1 for models, cases, execution, logging sections.

For conditions:

```python
# For each condition:
for cond_name, cond_cfg in config.conditions.items():
    # 1. Template field must be non-None
    assert cond_cfg.template is not None, f"{cond_name}: template is required"

    # 2. Structural rules based on condition category
    if cond_name in SIMPLE_CONDITIONS:
        assert cond_cfg.retry_template is None, f"{cond_name}: SIMPLE condition must not have retry_template"
        assert cond_cfg.next_template is None, f"{cond_name}: SIMPLE condition must not have next_template"
    elif cond_name in RETRY_CONDITIONS:
        assert cond_cfg.retry_template is not None, f"{cond_name}: RETRY condition must have retry_template"
        assert cond_cfg.next_template is None, f"{cond_name}: RETRY condition must not have next_template"
    elif cond_name in MULTISTEP_CONDITIONS:
        assert cond_cfg.retry_template is not None, f"{cond_name}: MULTISTEP must have retry_template"
        assert cond_cfg.next_template is not None, f"{cond_name}: MULTISTEP must have next_template"
```

### 4.2 Template Validation (at startup, via `preflight_validate_templates`)

Called once at startup after config is loaded:

1. Every registered template file exists on disk
2. No unregistered `.jinja2` files in `templates/` directory
3. No forbidden Jinja2 tags (for, macro, set, etc.) — only if/elif/else/endif
4. Every condition's `template`, `retry_template`, `next_template` references exist in `TEMPLATE_REGISTRY`
5. Dry-render every template with placeholder variables to verify Jinja2 syntax
6. Compute and store SHA-256 hashes for all templates (immutable after this point)

### 4.3 Runtime Validation (per render call)

`render(template_name, variables)` enforces:
- `template_name` exists in `TEMPLATE_REGISTRY`
- All `required_vars` are present in `variables`
- No extra vars beyond `required_vars` in `variables`
- Jinja2 `StrictUndefined` catches any template-level typos

Violation of any of these raises a specific exception (`TemplateMissingVarError`, `TemplateExtraVarError`, `TemplateNotFoundError`).

---

## 5. What Gets Replaced (REVISED)

| Current location | Current behavior | Config/template field that replaces it |
|-----------------|-----------------|----------------------------------------|
| `evaluator.py:142` | Hardcoded eval model | `models.evaluator.name` |
| `evaluator.py:232-234` | Hardcoded truncation limits | `models.evaluator.max_task_chars/code/reasoning` |
| `llm.py:66` | `USE_V2_OUTPUT_FORMAT = True` | `execution.v3_pipeline` settings |
| `prompt_view.py` | `TOKEN_BUDGETS` dict | `execution.token_budgets` |
| `execution.py` | `_get_token_budget()` hardcoded dict | `execution.token_budgets` |
| `runner.py` | CLI `--model` arg | `models.generation[].name` |
| `runner.py:28` | `LEG_EVAL_MODEL = "gpt-5-mini"` | `models.evaluator.name` |
| `prompts.py` | `CONDITION_MAP` + inline prompt strings | Conditions reference template names; `templates.py` renders |
| `condition_registry.py` | Condition definitions with flags | `conditions` section in YAML |
| `prompts.py:_format_code_files` | Prompt formatting logic | `templates/base.jinja2` via `{{ code_files_block }}` |

---

## 6. Prompt System Integration

### 6.1 Separation of Concerns

| Layer | Responsibility | Does NOT do |
|-------|---------------|-------------|
| YAML config | Names which template each condition uses | Contain prompt text |
| `templates.py` | Registry, rendering, hashing, validation | Choose which template to use |
| `templates/*.jinja2` | Prompt text with `{{ variable }}` placeholders | Control execution flow |
| Execution layer | Build variables dict, call `render()` | Know template content |

### 6.2 Adding a New Template

1. Create `templates/new_template.jinja2` with `{{ variable }}` placeholders
2. Register in `templates.py`:
   ```python
   register(TemplateSpec(
       name="new_template",
       path="templates/new_template.jinja2",
       required_vars=frozenset({"task", "code_files_block", "new_var"}),
   ))
   ```
3. Reference in YAML config condition:
   ```yaml
   new_condition:
     template: "new_template"
   ```
4. `preflight_validate_templates()` verifies everything at startup

### 6.3 Adding a New Condition

1. Add condition name to `constants.py` `ALL_CONDITIONS` and the appropriate category
2. Add template reference(s) in YAML config
3. Ensure referenced template(s) exist in `TEMPLATE_REGISTRY`
4. Ensure the execution layer knows how to build the variables dict for this condition

No changes to `templates.py` unless a new template is also needed.

---

## 7. Prompt Logging and Reproducibility

Every rendered prompt is logged with full provenance via `render_with_metadata()`:

```json
{
    "template_name": "retry",
    "template_hash": "a1b2c3d4e5f6...",
    "variables": {
        "task": "Fix the aliasing bug...",
        "code_files_block": "### FILE 1/2: ...",
        "previous_code": "def create_config...",
        "test_output": "FAILED: stale cache...",
        "failure_reason": "HIDDEN_DEPENDENCY",
        "step_number": "2"
    },
    "rendered_length": 3847
}
```

This record, combined with the template hash, allows exact reproduction of any prompt. The template hash changes if the template file is modified, making it impossible to silently change prompt content between runs.

---

## 8. Migration Path (REVISED)

**Phase 1 (done):** `templates.py` + `templates/` directory + `TEMPLATE_REGISTRY` exist. Tests pass. `constants.py` defines condition categories.

**Phase 2 (next):** Update `ConditionConfig` in `experiment_config.py` from single `prompt_template: str` to `template`, `retry_template`, `next_template` fields. Update YAML configs. Wire `get_template_for_condition()` into execution layer. Replace inline prompt construction in `prompts.py` with `render()` calls.

**Phase 3:** Remove `prompts.py` prompt-building functions that are now handled by templates. Remove `condition_registry.py` (conditions fully defined in config). Remove hardcoded `CONDITION_MAP` dispatch tables.
