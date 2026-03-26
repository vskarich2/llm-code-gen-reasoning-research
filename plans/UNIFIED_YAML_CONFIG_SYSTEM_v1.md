# Unified YAML Configuration System — Design Document

**Date:** 2026-03-26
**Status:** Design only. Not yet implemented.

---

## 1. Design Rationale

The current system has experimental parameters scattered across:
- `ablation_config.yaml` (partial — models and conditions only)
- `runner.py` CLI args (parallelism, case selection, quiet mode)
- `llm.py` hardcoded constants (evaluator model, temperature, `USE_V2_OUTPUT_FORMAT`)
- `execution.py` hardcoded constants (token budgets, retry behavior)
- `evaluator.py` hardcoded constants (classifier model name, truncation lengths, scoring thresholds)
- `prompts.py` hardcoded condition-to-template mapping
- `condition_registry.py` condition definitions
- `prompt_view.py` hardcoded `TOKEN_BUDGETS` dict

This design consolidates all of these into a single YAML file that is the sole source of truth for any experiment run.

---

## 2. Full YAML Schema (Complete Example)

```yaml
# ============================================================
# T3 Ablation Experiment Configuration
# ============================================================
# This file is the single source of truth for one experiment.
# Every parameter that affects results MUST be here.
# Nothing experimental is hardcoded in Python.

# ------------------------------------------------------------
# I. EXPERIMENT METADATA
# ------------------------------------------------------------
experiment:
  name: "retry_ablation_v3"
  description: "Retry-based interventions with LEG measurement on v2 cases"
  tags: ["ablation", "retry", "LEG", "v3_pipeline"]
  seed: 42
  # run_id is auto-generated at runtime as {name}_{model}_{timestamp}
  # but can be overridden:
  # run_id_override: "manual_run_001"

# ------------------------------------------------------------
# II. MODELS
# ------------------------------------------------------------
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

  # The LLM used to evaluate reasoning correctness (LEG classifier).
  # This was previously hardcoded in evaluator.py as "gpt-4.1-nano".
  evaluator:
    name: "gpt-4.1-nano"
    temperature: 0.0
    max_tokens: 1024
    # Truncation limits for classifier inputs:
    max_task_chars: 800
    max_code_chars: 2000
    max_reasoning_chars: 1000

  # The LLM used for failure classification (if separate from evaluator).
  # Set to null to use the evaluator model.
  failure_classifier:
    name: null  # defaults to evaluator.name

# ------------------------------------------------------------
# III. CONDITIONS
# ------------------------------------------------------------
# Each condition defines a complete experimental treatment.
# The runner iterates over (model x condition x case).
conditions:
  baseline:
    retry:
      enabled: false
    contract:
      enabled: false
    critique:
      enabled: false
    prompt_template: "baseline"

  diagnostic:
    retry:
      enabled: false
    contract:
      enabled: false
    critique:
      enabled: false
    prompt_template: "diagnostic"
    # Diagnostic nudge is injected via the template, not a flag.

  guardrail_strict:
    retry:
      enabled: false
    contract:
      enabled: false
    critique:
      enabled: false
    prompt_template: "guardrail_strict"

  retry_no_contract:
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: false
        include_previous_code: true
      stopping:
        stop_on_pass: true
        stop_on_stagnation: false
    contract:
      enabled: false
    critique:
      enabled: false
    prompt_template: "baseline"

  retry_with_contract:
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: false
        include_previous_code: true
      stopping:
        stop_on_pass: true
        stop_on_stagnation: false
    contract:
      enabled: true
      injection_point: "before_code"  # where contract text appears in prompt
    critique:
      enabled: false
    prompt_template: "contract_gated"

  retry_alignment:
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: true
        include_previous_code: true
      stopping:
        stop_on_pass: true
        stop_on_stagnation: false
    contract:
      enabled: true
      injection_point: "before_code"
    critique:
      enabled: true
      critique_model: null  # null = use generation model
    prompt_template: "alignment"

  retry_adaptive:
    retry:
      enabled: true
      max_attempts: 5
      feedback:
        include_test_output: true
        include_critique: true
        include_previous_code: true
      stopping:
        stop_on_pass: true
        stop_on_stagnation: true
        stagnation_window: 3  # stop after 3 consecutive failures with same error
    contract:
      enabled: true
      injection_point: "before_code"
    critique:
      enabled: true
      critique_model: null
    prompt_template: "adaptive"

# ------------------------------------------------------------
# IV. PROMPTS / TEMPLATES
# ------------------------------------------------------------
prompts:
  # Template directory relative to project root.
  template_dir: "prompt_templates/"

  # Named templates. Each maps to a file in template_dir
  # or an inline definition. The condition's prompt_template
  # field references these names.
  templates:
    baseline:
      file: "baseline.txt"
      # Templates use {task}, {codebase}, {output_format} placeholders.
      # The runner fills these from case data + output instruction.

    diagnostic:
      file: "diagnostic.txt"
      # Includes diagnostic nudge section.

    guardrail_strict:
      file: "guardrail_strict.txt"

    contract_gated:
      file: "contract_gated.txt"
      # Includes contract elicitation before code generation.

    alignment:
      file: "alignment.txt"

    adaptive:
      file: "adaptive.txt"

  # Sub-prompts used by templates (referenced via {sub_prompt_name}).
  sub_prompts:
    reasoning_instruction: |
      Analyze the bug step by step before writing code.
      Identify the root cause, then explain your fix.

    contract_elicitation: |
      Before writing code, state the invariant that the fix must preserve.
      Write it as a single assertion-style sentence.

    critique_instruction: |
      Review the previous attempt's code and test output.
      Identify what went wrong and how to fix it.
      Do not repeat the same mistake.

  # Output format instruction. V1 = single code blob, V2 = file-dict.
  output_format: "v2"  # "v1" | "v2"

# ------------------------------------------------------------
# V. CASE SELECTION
# ------------------------------------------------------------
cases:
  # Source file for case definitions.
  source: "cases_v2.json"

  # Selection mode: "all", "subset", or "filtered"
  mode: "all"

  # If mode is "subset", list explicit case IDs:
  # subset:
  #   - "alias_config_a"
  #   - "hidden_dep_multihop"
  #   - "l3_state_pipeline"

  # If mode is "filtered", specify filters:
  # filters:
  #   difficulty: ["A", "B"]           # only A and B difficulty
  #   family: ["alias_config", "stale_cache"]  # only these families
  #   min_files: 2                      # only multi-file cases
  #   exclude:
  #     - "check_then_act"             # skip specific cases

  # Max cases (for quick smoke tests). 0 = no limit.
  max_cases: 0

# ------------------------------------------------------------
# VI. RETRY CONFIGURATION (DEFAULTS)
# ------------------------------------------------------------
# These are defaults. Per-condition retry settings override them.
retry_defaults:
  max_attempts: 5
  feedback:
    include_test_output: true
    include_critique: false
    include_previous_code: true
  stopping:
    stop_on_pass: true
    stop_on_stagnation: false

# ------------------------------------------------------------
# VII. EVALUATION CONFIG
# ------------------------------------------------------------
evaluation:
  # Execution mode for running candidate code:
  #   "subprocess" = isolated subprocess per case (v3 pipeline)
  #   "in_process" = legacy exec() in parent process
  execution_mode: "subprocess"
  subprocess_timeout: 30  # seconds

  # Scoring:
  scoring:
    pass_threshold: 1.0  # score >= this means pass
    partial_credit: false  # if true, score can be between 0 and 1

  # LEG (Latent Execution Gap) detection:
  leg:
    enabled: true
    # Which error types are eligible for LEG analysis:
    eligible_error_types:
      - "logic_failure"
      - "execution_error"
      - "reconstruction_failure"  # secondary LEG only

  # Failure classification:
  failure_classification:
    enabled: true
    # Minimum confidence for classification:
    min_confidence: 0.5

  # Alignment (reasoning-vs-execution) classification:
  alignment:
    enabled: true
    # Categories produced:
    categories:
      - "true_success"    # reasoning correct + code correct
      - "leg"             # reasoning correct + code wrong
      - "lucky_fix"       # reasoning wrong + code correct
      - "true_failure"    # reasoning wrong + code wrong
      - "unclassified"    # classifier failed or insufficient data

# ------------------------------------------------------------
# VIII. EXECUTION CONFIG
# ------------------------------------------------------------
execution:
  # Number of parallel workers (1 = sequential).
  num_workers: 1

  # Token budget per model. Prompt exceeding this triggers reduction.
  token_budgets:
    "gpt-4.1-nano": 12000
    "gpt-4o-mini": 12000
    "gpt-5-mini": 16000
    default: 10000

  # V3 pipeline flags:
  v3_pipeline:
    import_summary: false  # include import graph summary in prompt
    # ^^^ Controlled here because calibration experiment (v3 plan)
    # must determine whether this is safe to enable.
    file_ordering: "dependency"  # "dependency" | "alphabetical" | "insertion"

# ------------------------------------------------------------
# IX. LOGGING CONFIG
# ------------------------------------------------------------
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR

  # What to store in the JSONL log:
  store:
    raw_prompts: true
    raw_outputs: true
    generated_code: true
    execution_traces: true
    reasoning_text: true

  # Output paths (relative to project root):
  output_dir: "logs/"
  # Per-run log is written to: {output_dir}/{run_id}.jsonl

  # Redis streaming (if Redis is available):
  redis:
    enabled: true
    url: "redis://localhost:6379/0"
    stream_maxlen: 100000

# ------------------------------------------------------------
# X. TRIALS
# ------------------------------------------------------------
# Number of independent trials per (model, condition_set) combination.
# Each trial gets a unique run_id and independent log.
trials: 1
```

---

## 3. Config Section Specifications

### 3.1 Section: `experiment`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `name` | string | **yes** | -- | Non-empty, valid filename chars |
| `description` | string | no | `""` | -- |
| `tags` | list[string] | no | `[]` | -- |
| `seed` | int | no | `null` | If set, >= 0 |
| `run_id_override` | string | no | `null` | If set, must be unique across runs |

### 3.2 Section: `models`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `generation` | list[model_spec] | **yes** | -- | At least one model |
| `generation[].name` | string | **yes** | -- | Non-empty |
| `generation[].temperature` | float | no | `0.0` | 0.0 - 2.0 |
| `generation[].max_tokens` | int | no | `4096` | > 0 |
| `generation[].top_p` | float | no | `1.0` | 0.0 - 1.0 |
| `evaluator.name` | string | **yes** | -- | **Must not be null.** This was previously hardcoded. |
| `evaluator.temperature` | float | no | `0.0` | 0.0 - 2.0 |
| `evaluator.max_tokens` | int | no | `1024` | > 0 |
| `evaluator.max_task_chars` | int | no | `800` | > 0 |
| `evaluator.max_code_chars` | int | no | `2000` | > 0 |
| `evaluator.max_reasoning_chars` | int | no | `1000` | > 0 |
| `failure_classifier.name` | string | no | `null` | If null, uses `evaluator.name` |

**Critical validation:** `evaluator.name` must not be null. The current bug where the evaluator model is hardcoded gets fixed by requiring this field.

### 3.3 Section: `conditions`

Each condition key is the condition name (used in results, logs, CLI).

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `retry.enabled` | bool | **yes** | -- | -- |
| `retry.max_attempts` | int | conditional | from `retry_defaults` | >= 1; required if retry.enabled |
| `retry.feedback.include_test_output` | bool | no | `true` | -- |
| `retry.feedback.include_critique` | bool | no | `false` | -- |
| `retry.feedback.include_previous_code` | bool | no | `true` | -- |
| `retry.stopping.stop_on_pass` | bool | no | `true` | -- |
| `retry.stopping.stop_on_stagnation` | bool | no | `false` | -- |
| `retry.stopping.stagnation_window` | int | no | `3` | >= 2 |
| `contract.enabled` | bool | no | `false` | -- |
| `contract.injection_point` | string | no | `"before_code"` | one of: `"before_code"`, `"after_task"`, `"system"` |
| `critique.enabled` | bool | no | `false` | requires `retry.enabled: true` |
| `critique.critique_model` | string | no | `null` | If null, uses generation model |
| `prompt_template` | string | **yes** | -- | Must reference a key in `prompts.templates` |

**Cross-field validation:**
- If `critique.enabled: true`, then `retry.enabled` must also be `true` (critique without retry is meaningless).
- If `contract.enabled: true` and `retry.enabled: false`, that is valid (single-attempt contract-gated generation).
- `prompt_template` must exist in `prompts.templates`.

### 3.4 Section: `prompts`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `template_dir` | string | no | `"prompt_templates/"` | Must be a valid directory |
| `templates` | map[string, template_spec] | **yes** | -- | At least one template |
| `templates.{name}.file` | string | **yes** | -- | File must exist in `template_dir` |
| `sub_prompts` | map[string, string] | no | `{}` | -- |
| `output_format` | string | no | `"v2"` | `"v1"` or `"v2"` |

**Template placeholder convention:** Templates use `{task}`, `{codebase}`, `{output_format}`, `{contract}`, `{critique}`, `{prior_code}`, `{test_output}`. The runner fills these from case data and condition settings. Unknown placeholders are left as-is (no silent stripping).

### 3.5 Section: `cases`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `source` | string | **yes** | -- | File must exist |
| `mode` | string | no | `"all"` | `"all"`, `"subset"`, `"filtered"` |
| `subset` | list[string] | conditional | -- | Required if mode is `"subset"` |
| `filters.difficulty` | list[string] | no | -- | Values from `["A", "B", "C", "L3"]` |
| `filters.family` | list[string] | no | -- | Must match actual family names |
| `filters.min_files` | int | no | `1` | >= 1 |
| `filters.exclude` | list[string] | no | `[]` | -- |
| `max_cases` | int | no | `0` | 0 = no limit |

**Validation:** If `mode: "subset"`, every case_id in `subset` must exist in the source file. Validated at load time, not at runtime.

### 3.6 Section: `retry_defaults`

Provides defaults for any condition that has `retry.enabled: true` but does not specify a given retry field. Structure mirrors the per-condition retry block. See 3.3.

### 3.7 Section: `evaluation`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `execution_mode` | string | no | `"subprocess"` | `"subprocess"` or `"in_process"` |
| `subprocess_timeout` | int | no | `30` | > 0 |
| `scoring.pass_threshold` | float | no | `1.0` | 0.0 - 1.0 |
| `scoring.partial_credit` | bool | no | `false` | -- |
| `leg.enabled` | bool | no | `true` | -- |
| `leg.eligible_error_types` | list[string] | no | see example | -- |
| `failure_classification.enabled` | bool | no | `true` | -- |
| `alignment.enabled` | bool | no | `true` | -- |

### 3.8 Section: `execution`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `num_workers` | int | no | `1` | >= 1 |
| `token_budgets` | map[string, int] | no | see example | All values > 0 |
| `token_budgets.default` | int | no | `10000` | > 0 |
| `v3_pipeline.import_summary` | bool | no | `false` | -- |
| `v3_pipeline.file_ordering` | string | no | `"dependency"` | `"dependency"`, `"alphabetical"`, `"insertion"` |

### 3.9 Section: `logging`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `level` | string | no | `"INFO"` | Standard Python log levels |
| `store.raw_prompts` | bool | no | `true` | -- |
| `store.raw_outputs` | bool | no | `true` | -- |
| `store.generated_code` | bool | no | `true` | -- |
| `store.execution_traces` | bool | no | `true` | -- |
| `store.reasoning_text` | bool | no | `true` | -- |
| `output_dir` | string | no | `"logs/"` | -- |
| `redis.enabled` | bool | no | `true` | -- |
| `redis.url` | string | no | `"redis://localhost:6379/0"` | -- |
| `redis.stream_maxlen` | int | no | `100000` | > 0 |

### 3.10 Section: `trials`

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `trials` | int | no | `1` | >= 1 |

---

## 4. Multi-Experiment Support

### 4.1 Directory Convention

```
configs/
  ablation_v1.yaml          # first experiment
  ablation_v2_retry.yaml    # retry-focused experiment
  ablation_v3_nano_only.yaml
  smoke_test.yaml           # quick validation with 3 cases
```

### 4.2 CLI Usage

```bash
# Run with a specific config
python runner.py --config configs/ablation_v2_retry.yaml

# Override individual fields from CLI
python runner.py --config configs/ablation_v2_retry.yaml \
  --override models.generation[0].name=gpt-5-mini \
  --override execution.num_workers=4 \
  --override cases.max_cases=5

# Quick smoke test
python runner.py --config configs/smoke_test.yaml
```

### 4.3 Override Rules

CLI overrides use dotted path notation. They are applied after YAML loading and before validation. An override that would produce an invalid config is rejected at validation time.

Overrides are logged in the run metadata so the exact configuration is reproducible:

```json
{
  "config_file": "configs/ablation_v2_retry.yaml",
  "config_sha256": "a1b2c3...",
  "cli_overrides": {
    "models.generation[0].name": "gpt-5-mini",
    "execution.num_workers": 4
  }
}
```

---

## 5. Validation Layer

### 5.1 Validation Stages

**Stage 1: Schema validation** (immediately after YAML parse)
- Required fields present
- Types correct (string, int, float, bool, list, map)
- Values within allowed ranges
- No unknown top-level keys (typo detection)

**Stage 2: Cross-reference validation** (after schema validation)
- Every `prompt_template` reference in `conditions` maps to an existing key in `prompts.templates`
- Every template file in `prompts.templates` exists on disk
- If `cases.mode == "subset"`, every case_id exists in the source file
- If `cases.mode == "filtered"`, filter values match actual data (e.g., difficulty levels)
- `evaluator.name` is not null
- If `critique.enabled`, then `retry.enabled` must be true

**Stage 3: Preflight validation** (at run start, before API calls)
- Generation model(s) reachable (optional quick probe)
- Cases load without errors
- Token budgets are defined for all generation models (or `default` exists)

### 5.2 Default Value Application

Defaults are applied bottom-up:
1. Built-in defaults (hardcoded in the validator, documented in schema)
2. `retry_defaults` section fills missing retry fields in conditions
3. YAML values override defaults
4. CLI overrides override YAML values

### 5.3 Validation Error Format

```
CONFIG VALIDATION FAILED:
  [ERROR] models.evaluator.name: required field is null
  [ERROR] conditions.retry_alignment.prompt_template: "alignment" not found in prompts.templates
  [WARN]  execution.token_budgets: no entry for model "gpt-5-mini", will use default (10000)
  [WARN]  cases.source: "cases_v2.json" has 58 cases but max_cases=5, only first 5 will run
```

Errors are fatal. Warnings are logged but non-blocking.

---

## 6. What Gets Replaced

| Current location | Current behavior | Config field that replaces it |
|-----------------|-----------------|-------------------------------|
| `evaluator.py:165` | Hardcoded `"gpt-4.1-nano"` as classifier model | `models.evaluator.name` |
| `evaluator.py:165-167` | Hardcoded truncation lengths (800, 2000, 1000) | `models.evaluator.max_task_chars`, `max_code_chars`, `max_reasoning_chars` |
| `llm.py:66` | `USE_V2_OUTPUT_FORMAT = True` | `prompts.output_format` |
| `prompt_view.py` | `TOKEN_BUDGETS` dict | `execution.token_budgets` |
| `execution.py` | `_get_token_budget()` hardcoded dict | `execution.token_budgets` |
| `runner.py` | CLI `--parallel` arg | `execution.num_workers` |
| `runner.py` | CLI `--model` arg | `models.generation[].name` |
| `runner.py` | `--conditions` arg with hardcoded known list | `conditions` section keys |
| `prompts.py` | `CONDITION_MAP` dict mapping condition names to builder functions | `conditions[].prompt_template` |
| `condition_registry.py` | Condition definitions with retry/contract/critique flags | `conditions` section |
| `ablation_config.yaml` (existing) | Partial config (models + conditions only) | Fully replaced by this unified config |

---

## 7. What Does NOT Go in Config

- **Case file contents** -- these are data, not config. The config points to them via `cases.source`.
- **Test function implementations** -- code, not config.
- **Reconstruction logic** -- algorithmic, not a knob.
- **Redis schema / key naming** -- infrastructure, not experimental parameter.
- **Python import paths** -- implementation detail.

The rule: if changing it could affect experimental results, it belongs in config. If it is purely implementation, it does not.

---

## 8. Migration Path

**Phase 1:** Create `configs/` directory with one complete config file. Implement `load_config(path)` function that parses YAML, applies defaults, validates. Thread the config object through `runner.py` -> `execution.py` -> `evaluator.py`. Replace hardcoded constants one at a time, starting with the most dangerous (evaluator model name).

**Phase 2:** Replace `ablation_config.yaml` references with the new unified config. Update CLI to accept `--config` instead of `--model`/`--conditions`/`--parallel` as separate flags. Keep old flags as `--override` shortcuts for one release.

**Phase 3:** Remove all hardcoded constants that are now in config. Delete `ablation_config.yaml`. Add config SHA to every log record for reproducibility.
