# T3 Code Generation Benchmark -- Deletion Audit

**Date:** 2026-03-27
**Method:** Full static import analysis (grep every .py file for imports, cross-reference shell scripts and YAML config)
**Scope:** All .py files in project root, scripts/, nudges/, templates/, tests/

---

## 1. File-Level Classifications

### Root-Level Python Files (35 files)

| File | Classification | Evidence |
|------|---------------|----------|
| `_stdlib.py` | **ACTIVE** | Imported by `parse.py`, `validate_cases_v2.py` |
| `call_logger.py` | **ACTIVE** | Imported by `execution.py`, `runner.py`, `llm.py`, `evaluator.py`, `retry_harness.py` |
| `condition_registry.py` | **ACTIVE** | Imported by `runner.py`; validates (case, condition) compatibility |
| `config.py` | **DEAD (SHADOWED)** | Zero production imports. Only imported by `tests/test_config.py`, `tests/test_integration_config_template.py`. Replaced by `experiment_config.py`. The code_snippets/reference_fixes `from config import` are case data, not system imports. |
| `constants.py` | **ACTIVE** | Imported by `runner.py`, `config.py` (dead), tests |
| `contract.py` | **ACTIVE** | Imported by `execution.py:636` (lazy), `tests/test_contract_gated.py` |
| `diff_gate.py` | **ACTIVE** | Imported by `execution.py:640` (lazy), `tests/test_contract_gated.py` |
| `eval_cases.py` | **LEGACY (MOSTLY DEAD)** | Only `_has` and `_low` are used (imported by `evaluator.py:322`). All 15 `_eval_*` functions and the `_EVALUATORS` dispatch table are DEAD -- never called from production. Tests actively verify `_EVALUATORS` is NOT imported. |
| `evaluator.py` | **ACTIVE** | Core evaluation path. Imported by `execution.py`, `retry_harness.py`, scripts |
| `exec_eval.py` | **ACTIVE** | Core execution evaluation. Imported by `evaluator.py`, `runner.py`, `preflight_check.py`, many tests |
| `execution.py` | **ACTIVE** | Core execution engine. Imported by `runner.py`, `retry_harness.py`, many tests |
| `experiment_config.py` | **ACTIVE** | Production config system. Imported by `runner.py`, `execution.py`, `llm.py`, `evaluator.py`, `prompt_view.py` |
| `failure_classifier.py` | **ACTIVE** | Imported by `evaluator.py`, `retry_harness.py`, `leg_evaluator.py`, tests |
| `leg_evaluator.py` | **ACTIVE** | Imported by `retry_harness.py:542,1318`, tests. LEG analysis module. |
| `leg_reduction.py` | **ACTIVE** | Imported by `execution.py:470,750`, tests |
| `live_metrics.py` | **ACTIVE** | Imported by `execution.py:143,177`, `scripts/update_dashboards.py`, `scripts/validate_smoke.py`, `scripts/merge_and_validate.py` |
| `llm_mock.py` | **ACTIVE** | Imported by `llm.py:117` (lazy, for mock mode) |
| `llm.py` | **ACTIVE** | Core LLM caller. Imported by `execution.py`, `evaluator.py`, `retry_harness.py`, `leg_evaluator.py` |
| `main.py` | **DEAD** | Placeholder stub (`print("Hello from t3-code-generation!")`). Not imported or referenced anywhere. |
| `parse.py` | **ACTIVE** | Core parser. Imported by `execution.py`, `exec_eval.py`, `retry_harness.py`, `leg_reduction.py`, many tests |
| `preflight_check.py` | **ACTIVE (STANDALONE)** | Not imported by any module. Run directly as `python preflight_check.py`. Pre-ablation validation script. |
| `prompt_view.py` | **DEAD** | Zero production imports. Only imported by `tests/test_pipeline_v3.py`. References `experiment_config.get_config().execution.token_budgets.get_budget()` which duplicates `execution.py:_get_token_budget()`. Never called in any active code path. |
| `prompts.py` | **ACTIVE** | Imported by `execution.py`, `contract.py`, `leg_reduction.py`, `retry_harness.py` |
| `reasoning_prompts.py` | **ACTIVE** | Imported by `execution.py:81,84,87` for structured/free_form/branching reasoning conditions |
| `reconstructor.py` | **ACTIVE** | Imported by `execution.py:282` (lazy), tests |
| `redis_metrics.py` | **ACTIVE (OPTIONAL)** | Imported by `execution.py:126` (lazy, fire-and-forget). Requires Redis server. Gracefully degrades if unavailable. |
| `retry_harness.py` | **ACTIVE** | Imported by `runner.py:202` for retry conditions |
| `runner_v2.py` | **DEAD (DELETED)** | File does not exist on disk. Shown in git status as modified but the working tree copy is gone. Was a thin wrapper calling `runner.main()`. |
| `runner.py` | **ACTIVE** | Entry point. Called by all shell scripts. |
| `scm_data.py` | **ACTIVE** | Imported by `scm_prompts.py`, `evaluator.py:388`, `condition_registry.py:168`, tests |
| `scm_prompts.py` | **ACTIVE** | Imported by `execution.py:62-77` for SCM conditions |
| `subprocess_eval.py` | **DEAD** | Zero production imports. Only imported by `tests/test_pipeline_v3.py:89,301`. Alternative evaluation path never wired into `execution.py` or `runner.py`. |
| `templates.py` | **DEAD (SHADOWED)** | Zero production imports. Only imported by `config.py` (itself dead) and test files. The actual prompt rendering uses `prompts.py` with inline string formatting, NOT Jinja2 templates. |
| `validate_cases_v2.py` | **ACTIVE** | Imported by `scripts/run_phase0.py`, `scripts/validate_smoke.py`, multiple tests. Also inlined in `run_ablation_leg_8t.sh`. |

### nudges/ Module (5 files)

| File | Classification | Evidence |
|------|---------------|----------|
| `nudges/__init__.py` | **ACTIVE** | Package init |
| `nudges/core.py` | **ACTIVE** | Operator definitions. Imported by `nudges/router.py` |
| `nudges/mapping.py` | **ACTIVE** | Case-to-operator mapping. Imported by `condition_registry.py`, `nudges/router.py` |
| `nudges/operators.py` | **ACTIVE** | Operator registry. Imported by `nudges/core.py`, `nudges/router.py`, `condition_registry.py` |
| `nudges/router.py` | **ACTIVE** | Router for nudge application. Imported by `execution.py:18` |

### templates/ Directory (7 Jinja2 files)

| File | Classification | Evidence |
|------|---------------|----------|
| `templates/base.jinja2` | **DEAD** | Registered in `templates.py` which is dead. Never rendered by production code. |
| `templates/classify.jinja2` | **DEAD** | Same -- `templates.py` is dead. |
| `templates/contract_code.jinja2` | **DEAD** | Same. |
| `templates/contract_elicit.jinja2` | **DEAD** | Same. |
| `templates/contract_retry.jinja2` | **DEAD** | Same. |
| `templates/repair_feedback.jinja2` | **DEAD** | Same. |
| `templates/retry.jinja2` | **DEAD** | Same. |

**Note:** The `experiment.yaml` config references template names like "base", "retry", "repair_feedback", "contract_elicit", "contract_code", "contract_retry" -- but these names are used as string labels in the config, not to render Jinja2 templates. The actual prompt construction is done by `prompts.py` using inline Python strings. The Jinja2 system was built but never connected to the production pipeline.

### scripts/ Directory (16 files)

| File | Classification | Evidence |
|------|---------------|----------|
| `scripts/run_ablation_leg_8t.sh` | **ACTIVE** | Primary ablation runner |
| `scripts/run_ablation_v2.sh` | **LEGACY** | Older ablation script (3 models x 2 trials). Superseded by `run_ablation_leg_8t.sh`. |
| `scripts/run_ablation.sh` | **LEGACY** | Simplest ablation wrapper. Single model, no multi-trial. |
| `scripts/run_tests.sh` | **ACTIVE** | Test runner |
| `scripts/validate_smoke.py` | **ACTIVE** | Called by `run_ablation_leg_8t.sh` for cost protection gate |
| `scripts/update_dashboards.py` | **ACTIVE** | Called by `run_ablation_leg_8t.sh` for live dashboard |
| `scripts/merge_and_validate.py` | **ACTIVE** | Referenced in `run_ablation_leg_8t.sh` post-run instructions |
| `scripts/paper_analysis.py` | **ACTIVE** | Referenced in `run_ablation_leg_8t.sh` post-run instructions. Has tests. |
| `scripts/run_phase0.py` | **ACTIVE** | Phase 0 evaluator measurement script |
| `scripts/canary_run.py` | **ACTIVE (STANDALONE)** | Pre-experiment validation. Not called from any shell script but referenced in audit docs. |
| `scripts/run_ablation_config.py` | **LEGACY** | Config-driven ablation runner. Not called from any shell script. Superseded by CLI-based approach in `run_ablation_leg_8t.sh`. |
| `scripts/redis_live_dashboard.py` | **ACTIVE (OPTIONAL)** | Redis-based live dashboard. Imported by `tests/test_redis_metrics.py`. |
| `scripts/shadow_analysis.py` | **LEGACY** | Post-hoc comparison tool. Known to have had syntax errors (per D_BUDIT_AUDIT). Not referenced by any other script. |
| `scripts/leg_ablation_analysis.py` | **ACTIVE (STANDALONE)** | Analysis script for LEG ablation results. Requires matplotlib/pandas. |
| `scripts/leg_regime_analysis.py` | **ACTIVE (STANDALONE)** | LEG regime analysis. References `failure_classifier.py`. |
| `scripts/extract_metadata.py` | **ACTIVE (STANDALONE)** | Log inspection utility. |
| `scripts/extract_responses.py` | **ACTIVE (STANDALONE)** | Response extraction utility. |
| `scripts/extraction_correctness_audit.py` | **ACTIVE (STANDALONE)** | Annotation correctness audit. |
| `scripts/test_invariant.py` | **ACTIVE (STANDALONE)** | Manual test runner for individual cases. |

---

## 2. Dead Code Detail

### 2.1 DEAD FILES (safe to delete)

| File | Lines | Reason |
|------|-------|--------|
| `main.py` | 6 | Placeholder stub. Zero imports, zero references. |
| `runner_v2.py` | ~10 | Already deleted from disk (git shows modified but file is gone). Was a trivial wrapper around `runner.main()`. |
| `prompt_view.py` | 273 | Never imported by production code. Only by `tests/test_pipeline_v3.py`. Duplicates `_get_token_budget` from `execution.py`. |
| `subprocess_eval.py` | 180 | Alternative eval path. Never wired into production. Only imported by `tests/test_pipeline_v3.py`. |
| `templates/` (7 files) | ~150 | Jinja2 templates never rendered. `templates.py` dead. Prompt rendering uses `prompts.py`. |

### 2.2 SHADOWED FILES (replaced by newer version)

| Dead File | Replacement | Evidence |
|-----------|-------------|----------|
| `config.py` (369 lines) | `experiment_config.py` | `config.py` imports `constants.py` and `templates.py`, produces `ExperimentConfig` dataclass. But production code (`runner.py`, `execution.py`, `llm.py`, `evaluator.py`) all import from `experiment_config.py` instead. `config.py` is only imported by its own tests. |
| `templates.py` (390+ lines) | `prompts.py` (inline strings) | `templates.py` provides Jinja2 rendering with `TEMPLATE_REGISTRY`. But `execution.py` builds prompts via `prompts.build_base_prompt()` which uses inline Python strings. The Jinja2 system is fully built but disconnected. |

### 2.3 DEAD FUNCTIONS IN ACTIVE FILES

#### eval_cases.py -- 15 dead evaluator functions + dead dispatch table

All `_eval_*` functions (719 lines of the 721-line file) are dead. Only `_has` (line 15) and `_low` (line 11) are used:

| Dead Function | Lines |
|---------------|-------|
| `_eval_hidden_dep` | 32-103 |
| `_eval_temporal` | 108-175 |
| `_eval_invariant` | 180-240 |
| `_eval_state_semantic` | 245-329 |
| `_eval_race_condition` | 334-361 |
| `_eval_idempotency` | 366-398 |
| `_eval_cache_order` | 403-432 |
| `_eval_partial_rollback` | 437-467 |
| `_eval_lazy_init` | 472-504 |
| `_eval_timing_dep` | 509-537 |
| `_eval_shared_ref` | 542-572 |
| `_eval_log_order` | 577-609 |
| `_eval_retry_causality` | 614-646 |
| `_eval_flag_drift` | 651-689 |
| `_eval_generic` | 694-700 |
| `_EVALUATORS` dispatch table | 705-720 |
| `_match_any` helper | 22-27 |

Tests in `test_hardening.py` explicitly verify that `_EVALUATORS` is NOT imported by `evaluator.py`. These heuristic evaluators were replaced by the LLM classifier in `evaluator.py:llm_classify()`.

**Recommendation:** Extract `_has` and `_low` into a tiny utility module (or inline into `evaluator.py`) and delete `eval_cases.py`.

#### prompts.py -- dead v1 formatter

| Dead Function | Lines | Reason |
|---------------|-------|--------|
| `_format_code_files_v1` | 230-236 | `_format_code_files()` always delegates to `_format_code_files_v2()`. v1 is never called. |

---

## 3. Duplicate Logic Groups

### 3.1 Duplicate Config Systems (3 systems)

| System | File | Status |
|--------|------|--------|
| **YAML config loader** | `config.py` | DEAD. Loads `experiment.yaml`, validates, produces frozen `ExperimentConfig` dataclass. |
| **Runtime config loader** | `experiment_config.py` | ACTIVE. The actual production config system. All production modules use this. |
| **YAML config file** | `experiment.yaml` | DEAD. Referenced only by `config.py` (dead) and `tests/test_integration_config_template.py`. Production uses `configs/default.yaml`. |

**Evidence of conflict:** `config.py` defines `ExperimentConfig` with fields `version, name, models, conditions, retry, execution, logging` and loads `experiment.yaml`. `experiment_config.py` defines its own config classes with fields like `ModelSpec, EvaluatorModelSpec, ModelsConfig, ExecutionConfig, OutputFormatConfig, TokenBudgetConfig` and loads `configs/default.yaml`. These are completely different data structures and different files -- `config.py` + `experiment.yaml` is an abandoned earlier attempt.

### 3.2 Duplicate Token Budget Functions

| Function | File | Status |
|----------|------|--------|
| `_get_token_budget(model)` | `execution.py:581` | **ACTIVE** -- called at line 541 |
| `get_token_budget(model)` | `prompt_view.py:119` | **DEAD** -- only called by `build_prompt_view()` which is dead |

Both call `experiment_config.get_config().execution.token_budgets.get_budget(model)`.

### 3.3 Four Logging Subsystems

The codebase has four separate logging mechanisms that operate in parallel:

| System | File | What It Logs | Status |
|--------|------|-------------|--------|
| **RunLogger** | `execution.py:806` | Per-call JSONL records to `{run_dir}/run.jsonl` | ACTIVE -- primary structured logging |
| **emit_event** | `live_metrics.py` | Per-evaluation events to `events.jsonl` | ACTIVE -- dashboard/analysis events |
| **call_logger** | `call_logger.py` | Per-LLM-call JSON to `{run_dir}/calls/` | ACTIVE -- raw prompt/response logging |
| **redis_metrics** | `redis_metrics.py` | Per-evaluation to Redis Stream | ACTIVE (optional) -- real-time dashboard |

These are deliberately separate (different granularity and purpose) but the execution path in `_emit_metrics_event` calls both `live_metrics.emit_event` AND `redis_metrics.emit_event`. This is by design, not duplication.

### 3.4 Duplicate Parsing Paths

| Parser | File | Purpose | Status |
|--------|------|---------|--------|
| `parse_model_response` | `parse.py:283` | Primary response parser | ACTIVE |
| `parse_leg_reduction_output` | `leg_reduction.py:271` | LEG-specific parser | ACTIVE (different format) |
| `parse_contract` | `contract.py:51` | Contract parsing | ACTIVE (different format) |
| `parse_classify_output` | `evaluator.py:93` | Classifier output parser | ACTIVE (different format) |
| `extract_code_from_raw` | `execution.py:267` | Wrapper around `parse_model_response` for CGE | ACTIVE (thin wrapper, not duplication) |

These are NOT duplicates -- they parse different response formats.

---

## 4. Unreachable Code Paths

### 4.1 Conditions Defined But Never Used in Current Ablation

The current active ablation script (`run_ablation_leg_8t.sh`) uses only:
- `baseline`
- `leg_reduction`

The following 24 conditions are defined in `constants.py:ALL_CONDITIONS` and fully implemented but NOT used in any active ablation script:

| Condition | Implementation | Category |
|-----------|---------------|----------|
| `diagnostic` | `execution.py` + `nudges/` | Nudge |
| `guardrail` | `execution.py` + `nudges/` | Nudge |
| `guardrail_strict` | `execution.py` + `nudges/` | Nudge |
| `counterfactual` | `execution.py` + `nudges/` | Nudge |
| `reason_then_act` | `execution.py` + `nudges/` | Nudge |
| `self_check` | `execution.py` + `nudges/` | Nudge |
| `counterfactual_check` | `execution.py` + `nudges/` | Nudge |
| `test_driven` | `execution.py` + `nudges/` | Nudge |
| `repair_loop` | `execution.py:run_repair_loop` | Repair |
| `scm_descriptive` | `scm_prompts.py` + `scm_data.py` | SCM |
| `scm_constrained` | `scm_prompts.py` + `scm_data.py` | SCM |
| `scm_constrained_evidence` | `scm_prompts.py` + `scm_data.py` | SCM |
| `scm_constrained_evidence_minimal` | `scm_prompts.py` + `scm_data.py` | SCM |
| `evidence_only` | `scm_prompts.py` + `scm_data.py` | SCM |
| `length_matched_control` | `scm_prompts.py` + `scm_data.py` | SCM |
| `structured_reasoning` | `reasoning_prompts.py` | Reasoning |
| `free_form_reasoning` | `reasoning_prompts.py` | Reasoning |
| `branching_reasoning` | `reasoning_prompts.py` | Reasoning |
| `contract_gated` | `contract.py` + `diff_gate.py` + `execution.py:run_contract_gated` | CGE |
| `retry_no_contract` | `retry_harness.py` | Retry |
| `retry_with_contract` | `retry_harness.py` | Retry |
| `retry_adaptive` | `retry_harness.py` | Retry |
| `retry_alignment` | `retry_harness.py` | Retry |

**Note:** These are NOT dead code -- they are latent experimental conditions that can be activated by changing the `--conditions` argument. They have tests and are structurally sound. However, they represent significant code mass that is currently dormant. The question is whether upcoming experiments will use them or whether they have been abandoned.

### 4.2 Legacy emit_event Path

In `execution.py:_emit_metrics_event()`, there is a "Legacy mode" branch (lines 175-207) that writes to the old shared `events.jsonl` when not in ablation mode. This path is reached only in non-ablation runs (manual single-case testing). It's not dead but is vestigial.

---

## 5. Template System Dead Code Chain

This is the largest connected dead code region:

```
experiment.yaml (config references template names)
       |
       v
config.py (loads experiment.yaml, validates templates)
       |
       v
templates.py (TEMPLATE_REGISTRY, Jinja2 rendering)
       |
       v
templates/*.jinja2 (7 template files)
```

NONE of this chain is used in production. The actual prompt flow is:

```
execution.py:build_prompt()
       |
       v
prompts.py:build_base_prompt() -> inline Python strings
       |
       +-> nudges/router.py (appends nudge text)
       +-> scm_prompts.py (builds SCM prompts)
       +-> reasoning_prompts.py (builds reasoning prompts)
       +-> contract.py (builds contract prompts)
       +-> leg_reduction.py (builds LEG prompts)
```

**Total dead lines in this chain:** ~900 lines (config.py: 369, templates.py: ~390, 7 jinja2 files: ~150)

---

## 6. Summary

### Bloat Inventory

| Category | Files | Estimated Lines |
|----------|-------|-----------------|
| Dead files (safe to delete) | `main.py`, `prompt_view.py`, `subprocess_eval.py` | ~460 |
| Shadowed files (replaced) | `config.py`, `templates.py` | ~760 |
| Dead template files | 7 Jinja2 files in `templates/` | ~150 |
| Dead functions in `eval_cases.py` | 15 evaluators + dispatch table + `_match_any` | ~690 |
| Dead function in `prompts.py` | `_format_code_files_v1` | ~7 |
| Dead config file | `experiment.yaml` (only used by dead `config.py`) | 81 |
| **Total dead/shadowed code** | | **~2,148 lines** |

### Action Items (Priority Order)

1. **DELETE `main.py`** -- 6-line placeholder, zero references.
2. **DELETE `prompt_view.py`** -- 273 lines, zero production imports, duplicates `execution.py:_get_token_budget`.
3. **DELETE `subprocess_eval.py`** -- 180 lines, alternative eval path never wired in.
4. **GUT `eval_cases.py`** -- Keep only `_has` and `_low` (move to evaluator.py or a utils module). Delete 690 lines of dead heuristic evaluators.
5. **DELETE `config.py` + `templates.py` + `templates/` directory + `experiment.yaml`** -- 900+ lines of abandoned Jinja2 config/rendering system. `experiment.yaml` is only referenced by dead `config.py` and its test. Production config lives in `configs/default.yaml` loaded by `experiment_config.py`. Confirmed: `runner.py` passes `--config configs/default.yaml` to `experiment_config.load_config()`.
6. **Clean up `runner_v2.py`** -- Already deleted from disk; clean git status.
7. **DELETE `prompts.py:_format_code_files_v1`** -- 7 dead lines, v2 is always used.

### Files That Are ACTIVE But Dormant

These files support conditions that are fully implemented but not used in the current ablation campaign. They should be KEPT but flagged as candidates for cleanup if those experiment arms are permanently abandoned:

- `contract.py` (153 lines) -- CGE condition
- `diff_gate.py` -- CGE condition
- `retry_harness.py` (~1500 lines) -- Retry conditions
- `scm_data.py` + `scm_prompts.py` -- SCM conditions
- `reasoning_prompts.py` -- Reasoning interface conditions
- `leg_evaluator.py` -- LEG analysis (used by retry_harness)

### Tests Affected by Deletions

If the dead files are deleted, these test files would need updates:

| Dead File | Tests That Import It |
|-----------|---------------------|
| `config.py` | `tests/test_config.py`, `tests/test_integration_config_template.py` |
| `templates.py` | `tests/test_templates.py`, `tests/test_integration_config_template.py` |
| `prompt_view.py` | `tests/test_pipeline_v3.py` (2 test methods) |
| `subprocess_eval.py` | `tests/test_pipeline_v3.py` (2 test methods) |
| `eval_cases.py` (gutted) | None (no test directly imports the dead functions) |
