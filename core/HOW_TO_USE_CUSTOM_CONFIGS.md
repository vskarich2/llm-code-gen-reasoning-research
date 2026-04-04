# How to Use Custom Configs

## Running an Experiment

```bash
.venv/bin/python -m core.pipeline.orchestration.runner --config core/config/config_storage/my_config.yaml
```

See `core/config/config_storage/example_custom_prompts.yaml` for a fully annotated example.

---

## Controlling Generation Prompts

The generation prompt is determined by the **condition name** in your config's `conditions:` section. Each condition maps to a list of `.j2` template components defined in `core/prompts/prompt_manifest.yaml`.

### Available conditions

| Condition | Components | What it does |
|---|---|---|
| `baseline_v2` | task_and_code + output_instruction_v3 | Task description + code + JSON output schema |
| `leg_reduction_lean_v2` | leg_reduction_lean_v2 | Lighter reasoning scaffold (root cause + fix strategy) |
| `leg_reduction_v2` | leg_reduction_v2 | Full reasoning scaffold (root cause + fix strategy + commitments + risk check) |
| `retry_bare_retry_v2` | (retry loop) | Retry with previous response, no critique |
| `retry_leg_critique_strict_v2` | (retry loop + critique_mismatch_v2) | Retry with 1-sentence mismatch critique |
| `retry_reasoning_only_critique_v1` | (retry loop + critique_reasoning_only) | Retry with reasoning-weakness critique |

### Using a condition in your config

```yaml
conditions:
  baseline_v2:
    retry:
      enabled: false
  leg_reduction_lean_v2:
    retry:
      enabled: false
```

List as many conditions as you want — the system runs all of them for every (model, case, trial) combination.

### Creating a new generation prompt

1. Create your template: `core/prompts/components/my_prompt.j2`
   - Available variables: `{{ task }}`, `{{ code_files_block }}`, `{{ file_keys_example }}`, `{{ schema_line }}`
   - Must instruct the model to return valid JSON with at minimum `root_cause`, `fix_strategy`, and `files` fields

2. Register it in `core/prompts/prompt_manifest.yaml`:
   ```yaml
   my_custom_condition:
     components: ["my_prompt"]
     nudge:
       type: "none"
     include_output_instruction: false
     label: "MY_CUSTOM"
   ```

3. Add to `core/registry/condition_registry.py` in `CONDITION_SPECS`:
   ```python
   "my_custom_condition": ConditionSpec(
       prompt_template="my_custom_condition",
       universal=True,
   ),
   ```

4. Use it in your config:
   ```yaml
   conditions:
     my_custom_condition:
       retry:
         enabled: false
   ```

---

## Controlling the Classifier Prompt

The classifier evaluates the model's reasoning against its generated code. The template is set via `evaluation.classifier_template` in your config.

### Available classifier templates

| Template | Dimensions | Description |
|---|---|---|
| `classify_reasoning_v2` (default) | mechanism_identified, commitments_extracted, commitments_satisfied, reasoning_code_alignment | Production 4-dimension scorer |
| `classify_reasoning` | mechanism_identified, invariant_identified, causal_chain_complete, fix_alignment, reasoning_code_alignment | Legacy 5-dimension scorer |

### Using a classifier in your config

```yaml
evaluation:
  classifier_template: "classify_reasoning_v2"
  classifier_mode: "grounded"  # "grounded" = classifier sees ground truth hints
```

### Creating a new classifier

1. Create your template: `core/prompts/components/my_classifier.j2`
   - Available variables: `{{ root_cause }}`, `{{ fix_strategy }}`, `{{ risk_check }}`, `{{ task }}`, `{{ code }}`, `{{ failure_types }}`, `{{ classifier_mode }}`
   - In grounded mode, also: `{{ ground_truth_failure_mode }}`, `{{ ground_truth_trap }}`, `{{ ground_truth_invariant }}`

2. Your template **must** output this exact format:
   ```
   DIM1;DIM2;DIM3;DIM4;FAILURE_TYPE
   HIGH
   Counterfactual: <sentence>
   Evidence: <bullets>
   Judgment: <sentences>
   ```
   Each dimension must be one of: `CORRECT`, `PARTIAL`, `WRONG`.
   The parser expects exactly 5 semicolon-separated fields on line 1 (4 dimensions + failure type).

3. Add metadata in `core/prompts/component_metadata.yaml`

4. Set in your config:
   ```yaml
   evaluation:
     classifier_template: "my_classifier"
   ```

---

## Other Config Options

### Models

```yaml
models:
  generation:
    - name: "gpt-4.1-nano"       # model for code generation
      temperature: 0.0
      max_tokens: 128000
    - name: "gpt-4o-mini"        # can list multiple — runs all
      temperature: 0.0
      max_tokens: 128000
  evaluator:
    name: "gpt-5-mini"           # model for classifier evaluation
    temperature: 0.0
    max_tokens: 128000
```

### Cases

```yaml
cases:
  source: "case_data/cases_v2.json"   # case definitions file
  case_ids:                            # optional: run only these cases
    - "partial_update_a"
    - "alias_config_a"
```

If `case_ids` is omitted, all cases in the source file are used.

### Trials and Parallelism

```yaml
trials: 10              # number of independent trials per (model, condition, case)

execution:
  num_workers: 8         # parallel worker subprocesses
  worker_stagger_seconds: 2
```

### Retry conditions

```yaml
conditions:
  retry_leg_critique_strict_v2:
    retry:
      enabled: true      # MUST be true for retry conditions
```

---

## File Locations

| What | Where |
|---|---|
| Config files | `core/config/config_storage/` |
| Generation prompt templates | `core/prompts/components/*.j2` |
| Classifier prompt templates | `core/prompts/components/classify_*.j2` |
| Prompt manifest (condition → components) | `core/prompts/prompt_manifest.yaml` |
| Component metadata | `core/prompts/component_metadata.yaml` |
| Condition registry | `core/registry/condition_registry.py` |
| Experiment config schema | `core/config/experiment_config.py` |
| Case definitions | `case_data/cases_v2.json` |
| Case source code (buggy files) | `case_data/code_snippets_v2/` |
| Case tests | `case_data/tests_v2/` |
| Output logs | `logs/<run_dir>/` |
