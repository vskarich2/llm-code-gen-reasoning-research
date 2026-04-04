# Config System Repair Plan V2.1

Strict patch revision of V2. All V2 content remains in force except where explicitly superseded below.

---

## Changes from V2

| Fix | V2 Defect | V2.1 Correction |
|---|---|---|
| 1 | `_known_exec -= {"import_summary", ...}` subtraction hack recreates schema duplication | Declarative CONFIG_SCHEMA mapping replaces all allow-lists and subtraction logic |
| 2 | `validate_prompts=False` disables enforcement entirely | Validation always runs; `validate_prompts` controls only warning-vs-crash for non-critical checks |
| 3 | `parts[-2]` positional assumption for logical key | Root-based extraction using `code_snippets_v2` anchor |
| 4 | Single-case smoke test insufficient coverage | Four-category smoke: baseline, retry, grounded-classifier, multi-file |
| 5 | Preflight unified test discovery but not execution path | Smoke gate calls `exec_canonical()` directly — same entrypoint as production |
| 6 | Logging insufficient for reproducibility | Mandatory prompt_hash, template_stack, config_hash, resolved_model_spec in every event |
| 7 | Strict parsing before YAML migration can brick repo | Dual-mode parser with `_STRICT_PARSING` toggle, removed after migration verified |
| 8 | No guarantee that every config knob is observable | CONFIG_LOG_COVERAGE registry with completeness assertion |

---

## FIX 1 — Declarative Schema Mapping (supersedes V2 Section 5.1)

### Design

File: `core/config/experiment_config.py`

Introduce `CONFIG_SCHEMA`: a single dict that maps every YAML path to its dataclass destination. This dict is the ONLY authority for what YAML keys are valid and where they route.

```python
# ── Schema mapping: YAML path → (dataclass_field_target, section) ──
# This is the SOLE authority for:
#   1. Which YAML keys are allowed in each section
#   2. Which dataclass field each YAML key populates
#   3. Cross-section routing (e.g., prompts.output_format → ExecutionConfig.output_format)
#
# Adding a field requires touching:
#   1. The dataclass (add typed field)
#   2. This dict (add routing entry)
# Nothing else.

CONFIG_SCHEMA = {
    # execution section
    "execution.num_workers":                     ("execution", "num_workers"),
    "execution.worker_stagger_seconds":          ("execution", "worker_stagger_seconds"),
    "execution.subprocess_timeout":              ("execution", "subprocess_timeout"),
    "execution.worker_timeout_seconds":          ("execution", "worker_timeout_seconds"),
    "execution.worker_graceful_shutdown_seconds": ("execution", "worker_graceful_shutdown_seconds"),
    "execution.mode":                            ("execution", "mode"),
    "execution.keep_eval_dirs":                  ("execution", "keep_eval_dirs"),
    "execution.validate_prompts":                ("execution", "validate_prompts"),
    "execution.recovery_execution":              ("execution", "recovery_execution"),
    "execution.max_orchestrator_attempts":        ("execution", "max_orchestrator_attempts"),
    "execution.anthropic_client_timeout":         ("execution", "anthropic_client_timeout"),
    "execution.anthropic_max_output_tokens":      ("execution", "anthropic_max_output_tokens"),
    # execution sub-objects (parsed specially, not 1:1 field mapping)
    "execution.token_budgets":                   ("execution", "_sub_token_budgets"),
    "execution.v3_pipeline":                     ("execution", "_sub_v3_pipeline"),
    # cross-section routing
    "execution.v3_pipeline.import_summary":      ("execution", "import_summary"),
    "execution.v3_pipeline.file_ordering":       ("execution", "file_ordering"),
    "prompts.output_format":                     ("execution", "output_format"),

    # evaluation section
    "evaluation.leg.enabled":                    ("evaluation", "leg_enabled"),
    "evaluation.failure_classification.enabled":  ("evaluation", "failure_classification_enabled"),
    "evaluation.alignment.enabled":              ("evaluation", "alignment_enabled"),
    "evaluation.classifier_mode":                ("evaluation", "classifier_mode"),
    "evaluation.reasoning_correct_mode":         ("evaluation", "reasoning_correct_mode"),
    "evaluation.classifier_template":            ("evaluation", "classifier_template"),
    "evaluation.classifier_schema_variant":      ("evaluation", "classifier_schema_variant"),
    "evaluation.generation_schema_variant":       ("evaluation", "generation_schema_variant"),

    # logging section
    "logging.level":                             ("logging", "level"),
    "logging.output_dir":                        ("logging", "output_dir"),
    "logging.redis.enabled":                     ("logging", "redis_enabled"),
    "logging.redis.url":                         ("logging", "redis_url"),
    "logging.redis.stream_maxlen":               ("logging", "redis_stream_maxlen"),

    # models section
    "models.no_temperature_prefixes":            ("models", "no_temperature_prefixes"),
}
```

### Derived allow-lists

Replace all `_KNOWN_*_FIELDS` sets and subtraction hacks with derivation from CONFIG_SCHEMA:

```python
def _allowed_yaml_keys(section_prefix: str) -> set[str]:
    """Derive allowed YAML keys for a section from CONFIG_SCHEMA.
    
    Returns the set of immediate child keys under the given section prefix.
    Example: _allowed_yaml_keys("execution") → {"num_workers", "token_budgets", ...}
    """
    prefix = section_prefix + "."
    keys = set()
    for yaml_path in CONFIG_SCHEMA:
        if yaml_path.startswith(prefix):
            remainder = yaml_path[len(prefix):]
            # Take only the immediate child (before next dot)
            keys.add(remainder.split(".")[0])
    return keys
```

Usage in `_parse_config()`:

```python
# execution section — unknown key detection
_exec_allowed = _allowed_yaml_keys("execution")
unknown = set(exec_raw.keys()) - _exec_allowed
if unknown:
    raise ValueError(f"Unknown fields in execution config: {unknown}. "
                     f"Valid: {sorted(_exec_allowed)}")

# evaluation section
_eval_allowed = _allowed_yaml_keys("evaluation")
unknown = set(eval_section.keys()) - _eval_allowed
if unknown:
    raise ValueError(f"Unknown fields in evaluation config: {unknown}. "
                     f"Valid: {sorted(_eval_allowed)}")

# logging section
_log_allowed = _allowed_yaml_keys("logging")
unknown = set(log_raw.keys()) - _log_allowed
if unknown:
    raise ValueError(f"Unknown fields in logging config: {unknown}. "
                     f"Valid: {sorted(_log_allowed)}")
```

### What is deleted

- `_KNOWN_EXEC_FIELDS` set (lines 412-417)
- `_known_yaml_keys_for()` function (V2 proposal — never ship this, replaced by `_allowed_yaml_keys`)
- `_EXEC_YAML_SPECIAL` set (V2 proposal)
- The subtraction line `_known_exec -= {"import_summary", "file_ordering", "output_format"}`
- All similar patterns for evaluation, logging, models sections

### Adding a new field

After V2.1, adding a config field requires exactly two changes:
1. Add the typed field to the dataclass (e.g., `ExecutionConfig`)
2. Add the routing entry to `CONFIG_SCHEMA`

The allow-list updates automatically. The parser uses `_require()` keyed by the schema. No third location to forget.

---

## FIX 2 — Prompt Metadata Validation Always Runs (supersedes V2 Section 6)

### Change

`validate_prompts` no longer gates enforcement. Metadata drift detection (`validate_template_against_metadata`, `validate_control_inputs`) runs unconditionally at registry load in all code paths.

The `validate_prompts` config field controls only:
- Verbose logging of validation steps (when True)
- Forbidden-tag checks (`validate_forbidden_tags`) — these reject advanced Jinja2 constructs (for/macro/set) which are style enforcement, not contract enforcement

Contract enforcement (undeclared variables, metadata drift, control input drift) always runs.

### Implementation

File: `core/pipeline/prompting/registry.py`, in `load()`:

```python
# BEFORE (V2 and current code)
if validate:
    validate_forbidden_tags(raw_template)
    validate_template_against_metadata(component)
    validate_control_inputs(component)

# AFTER (V2.1)
# Contract enforcement: ALWAYS runs. Not optional.
validate_template_against_metadata(component)
validate_control_inputs(component)

# Style enforcement: controlled by validate_prompts
if validate:
    validate_forbidden_tags(raw_template)
```

### Pipeline-level contract validation

Add `_validate_pipeline_contracts()` to `_smoke_gate()`:

```python
def _validate_pipeline_contracts(config):
    """Verify generation→classifier→evaluator contract chain.
    
    Generation output schema must produce fields the classifier consumes.
    Classifier output must produce fields the evaluator consumes.
    """
    reg = _get_compiler_registry()
    
    # 1. Generation output must include root_cause, fix_strategy, files
    #    (These become classifier inputs)
    gen_contract = {"root_cause", "fix_strategy", "files"}
    # Verified by output_instruction template which requires schema_line
    # containing these fields. The compiler's validate_output_contract()
    # checks this at compile time.
    
    # 2. Classifier output must produce mechanism_identified, 
    #    commitments_extracted, commitments_satisfied, reasoning_code_alignment
    #    (These become evaluator inputs in _compute_evaluation)
    classifier_template = config.evaluation.classifier_template
    comp = reg.get_component(classifier_template)
    classifier_exports = comp.exports
    required_exports = {"classification_output"}
    missing = required_exports - set(classifier_exports)
    if missing:
        raise RuntimeError(
            f"Pipeline contract violation: classifier template "
            f"'{classifier_template}' missing exports: {missing}"
        )
    
    # 3. Verify classifier schema variant matches parser expectations
    variant = config.evaluation.classifier_schema_variant
    valid_variants = {"v2_semicolon", "v3_json"}
    if variant not in valid_variants:
        raise RuntimeError(
            f"Pipeline contract violation: classifier_schema_variant "
            f"'{variant}' not in {valid_variants}"
        )
```

This check runs in `_smoke_gate()` as Gate 3.5 (after prompt compilation, before E2E smoke).

### Failure mode

- Undeclared template variable → `PromptUndeclaredVariableError` at registry load (always, even with `validate_prompts=False`)
- Metadata declares unreferenced variable → `PromptMetadataDriftError` at registry load (always)
- Pipeline contract violation → `RuntimeError` at smoke gate

---

## FIX 3 — Root-Based Logical File Key Generation (supersedes V2 Section 7.2)

### Change

Replace positional `parts[-2]` with explicit root anchor `code_snippets_v2`.

File: `core/pipeline/orchestration/runner.py`, in `load_cases()`:

```python
_LOGICAL_KEY_ROOT = "code_snippets_v2"

def _compute_logical_key(rel_path: str) -> str:
    """Derive stable prompt-facing key from storage path.
    
    Input:  "case_data/code_snippets_v2/alias_config_b/config.py"
    Output: "alias_config_b/config.py"
    
    Input:  "code_snippets_v2/alias_config_b/config.py"
    Output: "alias_config_b/config.py"
    
    Preserves arbitrary nesting below the root:
    Input:  "case_data/code_snippets_v2/deep/case/dir/file.py"
    Output: "deep/case/dir/file.py"
    """
    parts = Path(rel_path).parts
    if _LOGICAL_KEY_ROOT not in parts:
        raise ValueError(
            f"Cannot derive logical key: '{_LOGICAL_KEY_ROOT}' not found "
            f"in path '{rel_path}'. All code_files paths must contain "
            f"'{_LOGICAL_KEY_ROOT}' as a path component."
        )
    idx = parts.index(_LOGICAL_KEY_ROOT)
    logical_parts = parts[idx + 1:]
    if not logical_parts:
        raise ValueError(
            f"Cannot derive logical key: nothing after "
            f"'{_LOGICAL_KEY_ROOT}' in path '{rel_path}'"
        )
    return str(Path(*logical_parts))
```

Usage in `load_cases()`:

```python
logical_keys = {}
for rel_path, content in code_files_contents.items():
    lk = _compute_logical_key(rel_path)
    if lk in logical_keys:
        raise ValueError(
            f"Logical key collision: '{lk}' derived from both "
            f"'{rel_path}' and a previous path"
        )
    logical_keys[lk] = content
case["logical_file_keys"] = logical_keys
```

### What is deleted

- The `parts[-2]` / `parts[-1]` positional logic from V2
- The `assert lk.count("/") == 1` validation (too restrictive for nested cases)

### New validation

- `_LOGICAL_KEY_ROOT` must exist in path → crash if not
- Logical key must be non-empty → crash if not
- No collisions → crash if duplicate logical key

---

## FIX 4 — Coverage-Complete Smoke Gate (supersedes V2 Section 9)

### Smoke case selection

The smoke gate selects four cases, each exercising a distinct execution path. Selection is deterministic based on case metadata.

```python
def _select_smoke_cases(cases, config):
    """Select four cases covering distinct execution paths.
    
    Returns dict mapping category → case.
    Raises RuntimeError if any category cannot be filled.
    """
    smoke = {}
    conditions = list(config.conditions.keys())
    retry_conditions = [c for c in conditions if config.conditions[c].retry.enabled]
    
    # 1. Baseline: single-file case, non-retry condition
    for case in cases:
        if len(case["code_files"]) == 1:
            smoke["baseline_single_file"] = case
            break
    
    # 2. Multi-file: case with ≥3 code files
    for case in cases:
        if len(case["code_files"]) >= 3:
            smoke["multi_file"] = case
            break
    
    # 3. Any case (for retry path) — only if retry conditions exist
    if retry_conditions:
        smoke["retry"] = cases[0]
    
    # 4. Any case (for grounded classifier) — only if grounded mode
    if config.evaluation.classifier_mode == "grounded":
        smoke["grounded_classifier"] = cases[0]
    
    # Fallbacks: if single-file or multi-file not found, use first case
    if "baseline_single_file" not in smoke:
        smoke["baseline_single_file"] = cases[0]
    if "multi_file" not in smoke:
        smoke["multi_file"] = cases[-1] if len(cases) > 1 else cases[0]
    
    return smoke
```

### Revised smoke gate sequence

```python
def _smoke_gate(config, cases, run_dir):
    """Mandatory pre-launch validation. Aborts on any failure."""
    print("SMOKE GATE: starting...", flush=True)
    
    smoke_cases = _select_smoke_cases(cases, config)
    conditions = list(config.conditions.keys())
    retry_conditions = [c for c in conditions if config.conditions[c].retry.enabled]
    baseline_condition = conditions[0]
    
    # Gate 3: Compile ALL condition prompts (blind + grounded classifier)
    _smoke_compile_all_prompts(config)
    print("  GATE 3: prompt compilation OK", flush=True)
    
    # Gate 3.5: Pipeline contract validation
    _validate_pipeline_contracts(config)
    print("  GATE 3.5: pipeline contracts OK", flush=True)
    
    # Gate 5a: Baseline single-file E2E
    _smoke_execute_case(
        config, smoke_cases["baseline_single_file"],
        baseline_condition, run_dir, "baseline_single_file")
    print("  GATE 5a: baseline single-file E2E OK", flush=True)
    
    # Gate 5b: Multi-file E2E
    _smoke_execute_case(
        config, smoke_cases["multi_file"],
        baseline_condition, run_dir, "multi_file")
    print("  GATE 5b: multi-file E2E OK", flush=True)
    
    # Gate 5c: Retry E2E (conditional)
    if "retry" in smoke_cases:
        _smoke_execute_retry(
            config, smoke_cases["retry"],
            retry_conditions[0], run_dir)
        print("  GATE 5c: retry E2E OK", flush=True)
    
    # Gate 5d: Grounded classifier E2E (conditional)
    if "grounded_classifier" in smoke_cases:
        _smoke_execute_case(
            config, smoke_cases["grounded_classifier"],
            baseline_condition, run_dir, "grounded_classifier")
        print("  GATE 5d: grounded classifier E2E OK", flush=True)
    
    print("SMOKE GATE: all checks passed", flush=True)
```

### What constitutes failure

Each `_smoke_execute_case()` call invokes `exec_canonical()` (the real execution path — see Fix 5). The smoke passes if execution completes without infrastructure error. An `INVARIANT_FAILURE` (model got the answer wrong) is acceptable — the model is mocked. An `IMPORT_FAILURE`, `SUBPROCESS_CRASH`, `TIMEOUT` (on a 30s limit), `BUILD_FAILURE`, or `SCHEMA_VIOLATION` aborts the launch.

```python
_SMOKE_ACCEPTABLE = {"EXECUTION_SUCCESS", "INVARIANT_FAILURE", "INVARIANT_CRASH"}

def _smoke_execute_case(config, case, condition, run_dir, label):
    """Run one case through the real execution path. Abort on infra failure."""
    from core.pipeline.orchestration.execution_v2 import run_v2
    from core.logging_.logging_core import RunLogger
    
    smoke_dir = run_dir / "_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(smoke_dir, trial=0, run_id=f"smoke_{label}")
    logger.start_run(model=config.models.generation[0].name,
                     condition=condition)
    
    try:
        _, _, ev = run_v2(case, config.models.generation[0].name,
                          condition, logger)
    except Exception as e:
        raise RuntimeError(
            f"SMOKE GATE FAILED ({label}): {type(e).__name__}: {e}"
        ) from e
    
    category = ev.get("execution_category", "UNKNOWN")
    if category not in _SMOKE_ACCEPTABLE:
        raise RuntimeError(
            f"SMOKE GATE FAILED ({label}): execution_category={category}, "
            f"reasons={ev.get('reasons', [])}"
        )
```

---

## FIX 5 — Preflight and Execution Share Identical Entrypoint (supersedes V2 Section 8)

### Canonical execution entrypoint

The single canonical entrypoint for executing a case is:

```
execution_v2.run_v2(case, model, condition, logger, case_start_eid)
```

This function owns: prompt → call_model → parse → reconstruct → exec_canonical → classify → metrics → log.

### Call sites after V2.1

| Caller | Function | Purpose |
|---|---|---|
| `runner.py:_run_one_inner()` | `run_v2(case, model, condition, logger, eid)` | Production single-case execution |
| `runner.py:_run_one_inner()` | `run_retry_v2(case, model, condition, logger, eid)` | Production retry execution |
| `orchestrate.py:_smoke_gate()` | `run_v2(case, model, condition, logger)` | Smoke E2E — same function |
| `orchestrate.py:_smoke_gate()` | `run_retry_v2(case, model, condition, logger)` | Smoke retry — same function |

The smoke gate does NOT simulate execution. It calls the exact same `run_v2()` and `run_retry_v2()` that production uses. If production would fail, the smoke fails first.

### What is removed

- No alternative execution paths exist
- No "lite" or "simulated" preflight execution
- Preflight asset/test discovery checks remain (Gates 2, 4) but they are necessary-not-sufficient; the smoke gate (Gate 5) is the sufficient check

### V2 test discovery unification (retained)

V2's change to `run_case.py` (switching from `importlib.import_module` to `spec_from_file_location`) is retained. This ensures test discovery congruence between preflight and subprocess execution. Fix 5 adds execution-path congruence on top of that.

---

## FIX 6 — Reproducibility Logging (supersedes V2 Section 10)

### Required fields per event

Every case-end event must include these fields so that the run is fully reproducible from logs alone:

| Field | Location | Computation |
|---|---|---|
| `config_hash` | `ev["config"]` | `config._config_sha256` (already computed at load time) |
| `prompt_hash` | `ev["prompt_meta"]["prompt_hash"]` | SHA-256 of final prompt string (already computed in `_render_generation_prompt`) |
| `template_stack` | `ev["prompt_meta"]["template_stack"]` | Ordered list of component names from compiled prompt |
| `resolved_model_spec` | `ev["model_spec"]` | `{"name": model, "temperature": spec.temperature, "max_tokens": spec.max_tokens, "top_p": spec.top_p}` |
| `logical_file_keys` | `ev["prompt_meta"]["logical_file_keys"]` | List of prompt-facing keys used |
| `retry_max_attempts` | `ev["retry_config"]` (retry only) | `config.conditions[cond].retry.max_attempts` |
| `retry_max_total_seconds` | `ev["retry_config"]` (retry only) | `config.conditions[cond].retry.max_total_seconds` |
| `classifier_mode` | `ev["classification"]["classifier_mode"]` | `config.evaluation.classifier_mode` |
| `classifier_template` | `ev["classification"]["classifier_template"]` | `config.evaluation.classifier_template` |
| `classifier_schema_variant` | `ev["classification"]["classifier_schema_variant"]` | `config.evaluation.classifier_schema_variant` |
| `subprocess_timeout` | `ev["execution"]["subprocess_timeout"]` | `config.execution.subprocess_timeout` |
| `recovery_execution_enabled` | `ev["reconstruction"]["recovery_execution_enabled"]` | `config.execution.recovery_execution` |
| `anthropic_max_output_tokens` | `ev["model_spec"]["anthropic_max_output_tokens"]` | For Anthropic models only |

### Implementation

**In `execution_v2.py:_assemble_result()`**, add:

```python
ev["config"] = {
    "config_hash": config._config_sha256,
    "config_path": config._config_path,
}

ev["model_spec"] = {
    "name": model,
    "temperature": spec.temperature,
    "max_tokens": spec.max_tokens,
    "top_p": spec.top_p,
}
```

**In `execution_v2.py:_render_generation_prompt()`**, extend `prompt_meta`:

```python
prompt_meta["template_stack"] = list(components)  # ordered component names
prompt_meta["logical_file_keys"] = list(case["logical_file_keys"].keys())
```

**In `retry_v2.py:run_retry_v2()`**, at the start of the function:

```python
ev["retry_config"] = {
    "max_attempts": max_iterations,
    "max_total_seconds": max_total_seconds,
    "condition": condition,
}
```

### Hash computation

- `config_hash`: already `hashlib.sha256(raw_yaml_text).hexdigest()` — set at load time
- `prompt_hash`: already `hashlib.sha256(final_prompt.encode()).hexdigest()` — set in `CompiledPrompt`
- All hashes are deterministic given the same inputs

---

## FIX 7 — Safe Migration Strategy (new section, inserted before V2 Step 4)

### Problem

If strict parsing (`_require()`) is enabled before all 102 YAML files are migrated, any config load from an un-migrated file crashes. This bricks the repo for anyone using a non-default config.

### Solution: Dual-mode parser

File: `core/config/experiment_config.py`

Add a module-level toggle:

```python
# Migration toggle. Set to True after all YAML configs are verified.
# When False: missing keys emit WARNING and use schema default.
# When True: missing keys raise ValueError.
# This toggle is TEMPORARY. Remove it after migration step is complete.
_STRICT_PARSING = False
```

Modify `_require()`:

```python
def _require(d: dict, key: str, section: str, *, schema_default=_SENTINEL):
    """Strict config extraction with migration support.
    
    When _STRICT_PARSING is True: crash on missing key.
    When _STRICT_PARSING is False: warn and use schema_default.
    schema_default is ONLY used during migration. It must match
    the value that will be in the migrated YAML.
    """
    if key in d:
        return d[key]
    if _STRICT_PARSING:
        raise ValueError(
            f"CONFIG ERROR: {section}.{key} is REQUIRED but missing from YAML."
        )
    if schema_default is _SENTINEL:
        raise ValueError(
            f"CONFIG ERROR: {section}.{key} missing and no schema_default "
            f"provided for migration mode."
        )
    _log.warning(
        "CONFIG MIGRATION: %s.%s missing from YAML, using schema default: %r. "
        "This will become a fatal error when _STRICT_PARSING is enabled.",
        section, key, schema_default,
    )
    return schema_default

_SENTINEL = object()
```

### Migration sequence

1. **Step 3a**: Set `_STRICT_PARSING = False`. Deploy `_require()` with `schema_default` for every field. All existing configs load with warnings for missing fields.
2. **Step 3b**: Run `scripts/migrate_yaml_configs.py` to add missing fields to all 102 YAML files.
3. **Step 3c**: Verify every YAML loads without warnings: `for f in core/config/config_storage/*.yaml; do python -c "from core.config.experiment_config import load_config; load_config('$f')" 2>&1 | grep "MIGRATION" && echo "FAIL: $f" && exit 1; done`
4. **Step 3d**: Set `_STRICT_PARSING = True`. Remove all `schema_default=` arguments from `_require()` calls. Remove `_STRICT_PARSING` toggle, `_SENTINEL`, and the migration codepath from `_require()`.

After step 3d, `_require()` is the strict version with no fallback. The migration code is deleted.

---

## FIX 8 — Config→Log Coverage Invariant (new section)

### Design

File: `core/config/experiment_config.py`

Define a registry mapping every config field to its log location:

```python
CONFIG_LOG_COVERAGE = {
    # execution fields
    "execution.num_workers":                     "run_start.num_workers",
    "execution.subprocess_timeout":              "ev.execution.subprocess_timeout",
    "execution.worker_timeout_seconds":          "run_start.worker_timeout_seconds",
    "execution.worker_graceful_shutdown_seconds": "run_start.worker_graceful_shutdown_seconds",
    "execution.worker_stagger_seconds":          "run_start.worker_stagger_seconds",
    "execution.mode":                            "run_start.execution_mode",
    "execution.keep_eval_dirs":                  "NON_OBSERVABLE:infrastructure_only",
    "execution.validate_prompts":                "run_start.validate_prompts",
    "execution.recovery_execution":              "ev.reconstruction.recovery_execution_enabled",
    "execution.max_orchestrator_attempts":        "NON_OBSERVABLE:orchestrator_internal",
    "execution.anthropic_client_timeout":         "ev.model_spec.anthropic_client_timeout",
    "execution.anthropic_max_output_tokens":      "ev.model_spec.anthropic_max_output_tokens",
    "execution.import_summary":                  "NON_OBSERVABLE:prompt_construction_only",
    "execution.file_ordering":                   "NON_OBSERVABLE:prompt_construction_only",
    "execution.output_format":                   "run_start.output_format",
    # evaluation fields
    "evaluation.classifier_mode":                "ev.classification.classifier_mode",
    "evaluation.classifier_template":            "ev.classification.classifier_template",
    "evaluation.classifier_schema_variant":      "ev.classification.classifier_schema_variant",
    "evaluation.reasoning_correct_mode":         "ev.classification.reasoning_correct_mode",
    "evaluation.generation_schema_variant":       "NON_OBSERVABLE:parser_internal",
    "evaluation.leg_enabled":                    "run_start.leg_enabled",
    "evaluation.failure_classification_enabled":  "run_start.failure_classification_enabled",
    "evaluation.alignment_enabled":              "run_start.alignment_enabled",
    # model fields
    "models.generation[].temperature":           "ev.model_spec.temperature",
    "models.generation[].max_tokens":            "ev.model_spec.max_tokens",
    "models.generation[].top_p":                 "ev.model_spec.top_p",
    "models.evaluator.name":                     "run_start.evaluator_model",
    "models.no_temperature_prefixes":            "NON_OBSERVABLE:model_call_internal",
    # retry fields (per-condition)
    "retry.max_attempts":                        "ev.retry_config.max_attempts",
    "retry.max_total_seconds":                   "ev.retry_config.max_total_seconds",
    # logging fields
    "logging.level":                             "NON_OBSERVABLE:infrastructure_only",
    "logging.output_dir":                        "NON_OBSERVABLE:infrastructure_only",
    "logging.redis_enabled":                     "NON_OBSERVABLE:infrastructure_only",
    # run fields
    "run.run_dir":                               "run_start.run_dir",
    "run.trial":                                 "run_start.trial",
    "run.run_id":                                "run_start.run_id",
    # top-level
    "config_hash":                               "ev.config.config_hash",
}
```

### Rules

- Every config field must appear in CONFIG_LOG_COVERAGE
- Fields marked `NON_OBSERVABLE:*` are explicitly acknowledged as not logged, with a reason
- All other fields must map to a log path that is actually populated

### Enforcement

Add to `scripts/audit_config_usage.py`:

```python
def scan_config_log_coverage():
    """Verify every CONFIG_SCHEMA entry has a CONFIG_LOG_COVERAGE entry."""
    from core.config.experiment_config import CONFIG_SCHEMA, CONFIG_LOG_COVERAGE
    
    issues = []
    for yaml_path in CONFIG_SCHEMA:
        section, field = CONFIG_SCHEMA[yaml_path]
        if field.startswith("_sub_"):
            continue  # Sub-objects are covered by their child fields
        if yaml_path not in CONFIG_LOG_COVERAGE:
            issues.append(f"CONFIG_LOG_COVERAGE missing entry for: {yaml_path}")
    
    return issues
```

This check runs as part of the audit script. Missing coverage entries cause exit code 1.

---

## Updated Migration Plan (supersedes V2 Section 13)

### Step 1: Add infrastructure (no behavioral change)

File: `experiment_config.py`
- Add `CONFIG_SCHEMA` dict
- Add `CONFIG_LOG_COVERAGE` dict
- Add `_allowed_yaml_keys()` function
- Add `_require()` with `_STRICT_PARSING = False` and `schema_default` support
- Add `_require_section()`
- Delete `_KNOWN_EXEC_FIELDS`

### Step 2: Update default.yaml

File: `default.yaml`
- Add all missing fields (execution, evaluation, models)
- Remove misplaced/dead fields
- Verify: `load_config("default.yaml")` succeeds with zero warnings

### Step 3: Migrate all YAML configs (dual-mode)

File: `scripts/migrate_yaml_configs.py` + all 102 YAML files
- Step 3a: `_STRICT_PARSING = False`, deploy `_require()` with `schema_default`
- Step 3b: Run migration script on all 102 files
- Step 3c: Verify zero migration warnings for every file
- Step 3d: `_STRICT_PARSING = True`, remove migration codepath

### Step 4: Add new dataclass fields, remove defaults

File: `experiment_config.py`
- Add `recovery_execution`, `max_orchestrator_attempts`, `anthropic_client_timeout`, `anthropic_max_output_tokens` to ExecutionConfig
- Change `ModelsConfig.no_temperature_prefixes` to field
- Delete dead LoggingConfig fields
- Remove all `= value` defaults from ExecutionConfig, EvaluationConfig, LoggingConfig
- Replace all `.get()` with `_require()` (strict, no schema_default — migration is done)
- Add unknown-key detection using `_allowed_yaml_keys()`
- Update `config_to_dict()`

### Step 5: Make prompt validation unconditional

File: `registry.py`
- Contract checks (metadata drift, control inputs) always run
- `validate_prompts` controls only forbidden-tag style checks

### Step 6: Rewire consumers

Files: `retry_v2.py`, `orchestrate.py`, `exec_canonical.py`, `execution_v2.py`, `llm.py`
- Delete module constants, replace with config reads
- Remove getattr/hasattr patterns
- Delete dead functions from llm.py

### Step 7: Logical file keys (root-based)

File: `runner.py`
- Add `_compute_logical_key()` with `_LOGICAL_KEY_ROOT = "code_snippets_v2"` anchor
- Update `execution_v2.py` to use logical keys

### Step 8: Unify test discovery

File: `run_case.py`
- Switch to `spec_from_file_location()`

### Step 9: Add smoke gate (coverage-complete)

File: `orchestrate.py`
- Add `_select_smoke_cases()` (4 categories)
- Add `_smoke_gate()` with Gates 3, 3.5, 5a-5d
- Smoke calls `run_v2()` and `run_retry_v2()` — the real entrypoints

### Step 10: Add reproducibility logging

Files: `execution_v2.py`, `retry_v2.py`, `llm.py`
- Add config_hash, prompt_hash, template_stack, resolved_model_spec, logical_file_keys
- Add classifier config fields, retry config fields, subprocess timeout

### Step 11: Update audit script

File: `scripts/audit_config_usage.py`
- Add CONFIG_LOG_COVERAGE completeness check
- Add all forbidden-pattern checks from V2

### Step 12: Validate

Run all checks from updated validation matrix.

---

## Updated Validation Matrix (supersedes V2 Section 14)

All V2 checks retained. New V2.1 checks added:

| # | Check | Pass Criterion |
|---|---|---|
| 22 | CONFIG_SCHEMA covers every dataclass field | `_allowed_yaml_keys()` returns superset of actual YAML keys for every section |
| 23 | No `_KNOWN_*_FIELDS` sets in codebase | `grep -rn "_KNOWN_.*_FIELDS" core/` → zero matches |
| 24 | No subtraction hacks in parser | `grep -n " -= {" core/config/experiment_config.py` → zero matches |
| 25 | Metadata drift detection runs with `validate_prompts=False` | Set `validate_prompts: false`, add undeclared var to template → still crashes at load |
| 26 | Pipeline contract validation passes | `_validate_pipeline_contracts(config)` runs without error |
| 27 | Logical key root-based derivation | Path `"x/y/code_snippets_v2/deep/case/file.py"` → logical key `"deep/case/file.py"` |
| 28 | Logical key crashes on missing root | Path `"some/other/path/file.py"` → ValueError mentioning `code_snippets_v2` |
| 29 | Smoke gate selects 4 categories | `_select_smoke_cases()` returns dict with ≥2 keys (baseline + multi-file always present) |
| 30 | Smoke gate calls real `run_v2()` | Inspect call stack: `_smoke_execute_case → run_v2 → exec_canonical` (not simulated) |
| 31 | CONFIG_LOG_COVERAGE complete | `scan_config_log_coverage()` returns zero issues |
| 32 | Migration toggle removed | `grep -n "_STRICT_PARSING\|schema_default" core/config/experiment_config.py` → zero matches |
| 33 | Every event has config_hash | Sample 10 events from a run, verify `ev["config"]["config_hash"]` is present and matches config SHA |

---

## Updated Closure Table (addendum to V2 Section 15)

All V2 closures remain valid. Additional closures for V2.1 corrections:

| Fix | Issue | Closed By |
|---|---|---|
| Fix 1 | Subtraction hack `_known_exec -= {...}` | CONFIG_SCHEMA declarative mapping (Step 1) |
| Fix 2 | `validate_prompts=False` disables contract enforcement | Registry always runs drift checks (Step 5) |
| Fix 2 | No pipeline-level contract validation | `_validate_pipeline_contracts()` in smoke gate (Step 9) |
| Fix 3 | `parts[-2]` positional assumption | `_compute_logical_key()` with root anchor (Step 7) |
| Fix 4 | Single-case smoke insufficient | 4-category smoke selection (Step 9) |
| Fix 5 | Preflight does not exercise real execution path | Smoke calls `run_v2()` directly (Step 9) |
| Fix 6 | Logging insufficient for reproducibility | 13 mandatory fields per event (Step 10) |
| Fix 7 | Strict parsing before migration bricks repo | Dual-mode `_STRICT_PARSING` toggle, removed after migration (Step 3) |
| Fix 8 | No guarantee config knobs are observable | CONFIG_LOG_COVERAGE registry with audit check (Step 11) |
