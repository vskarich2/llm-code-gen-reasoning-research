# Config System Repair Plan V2

Reference: `config_forensic_audit_v1.md` (31 violations), `config_system_repair_plan_v1.md` (predecessor)

---

## 1. Executive Diagnosis

V1 was insufficient. It treated the problem as "remove Python defaults and wire YAML fields." The actual failure surface is broader:

1. **Duplicated schema authority.** The `ExecutionConfig` dataclass defines 12 fields. `_KNOWN_EXEC_FIELDS` is a hand-maintained allow-list of 10 field names that must match. Adding `validate_prompts` to the dataclass and parser but forgetting the allow-list caused a total launch failure for 1,740 work items. V1 noted this allow-list but did not eliminate it.

2. **Prompt metadata drift.** Template variables and metadata declarations can diverge. The existing drift detection (`validate_template_against_metadata`) is gated behind `validate_prompts` config, which is itself subject to the schema duplication problem. The drift detection covers undeclared variables and unreferenced declarations, but conditional-group variables (grounded mode) are only checked when the condition evaluates to true at compile time. V1 did not address this.

3. **Divergent preflight/execution paths.** Preflight uses `importlib.util.spec_from_file_location()` (file-based, no sys.path dependency). Execution subprocess uses `importlib.import_module("tests_v2.test_{family}")` (package-based, requires sys.path injection). A missing `import os` in `run_case.py` or a broken PYTHONPATH causes execution to fail while preflight passed. V1 did not address this.

4. **Path contract instability.** `cases_v2.json` `code_files` paths serve dual duty: filesystem resolution AND prompt-facing output schema keys. A storage path rename (e.g., adding `case_data/` prefix) silently changes the model's output contract. Execution only uses basenames, so it works, but the model returns keys with the new prefix, making old analysis scripts break. V1 did not address this.

5. **Missing launch gate.** No end-to-end smoke test runs before worker fan-out. Preflight checks asset existence and test discovery but never actually executes a case. A trivial runtime error (missing import, bad PYTHONPATH) only surfaces after 1,740 work items are dispatched. V1 did not address this.

---

## 2. Scope Boundary

**In scope:**
- Config source-of-truth repair (all 31 audit violations)
- Parser strictness (`_require()` replacing `.get()`)
- Schema derivation (eliminate `_KNOWN_EXEC_FIELDS` and similar manual allow-lists)
- Consumer rewiring (retry_v2, orchestrate, exec_canonical, llm, execution_v2)
- Path authority cleanup (separate storage path from prompt-facing key)
- Prompt contract stabilization (metadata drift enforcement)
- Unified test discovery (single mechanism for preflight and execution)
- Smoke-gate enforcement (mandatory pre-launch end-to-end test)
- Launch-time validation (directory creation, manifest integrity)
- Logging visibility for config-sensitive behavior

**Not in scope:**
- Prompt content changes (template text, component logic)
- New benchmark cases or families
- Analysis scripts or visualization
- Test invariant strengthening
- AST evaluation logic

---

## 3. Failure-Class Mapping

| Failure Class | Examples | Root Cause | Architectural Fix | Enforcement |
|---|---|---|---|---|
| **Shadow override** | V1/V2: retry_v2.py MAX_ITERATIONS=3 shadows config max_attempts=5 | Module constants written before config system existed | Delete constants, read from config at call site | Grep-based CI check: no `MAX_` constants in orchestration files |
| **Silent drop** | V3: default.yaml evaluation.subprocess_timeout ignored; V22/V23: logging.store.generated_code ignored | Parser reads from wrong section; YAML field has no parser extraction | Unknown-key detection per section; auto-derive known-key sets from dataclass | `_validate_known_keys()` at load time; no manual allow-lists |
| **Hardcoded default** | V4-V10, V11-V15: 14 fields with Python defaults, absent from default.yaml | `.get(key, default)` pattern permits YAML omission | `_require()` for all extractions; no-default dataclasses | TypeError if parser omits field; ValueError if YAML omits field |
| **Dead config** | V24/V25: store_raw_prompts parsed but never read; V28/V29: dead functions | Fields/functions created speculatively, never wired | Delete dead fields from dataclass; delete dead functions from llm.py | Audit script checks every dataclass field has ≥1 consumer |
| **Divergent source** | V26: getattr(config.execution, "num_workers", 4) fallback ≠ schema default 1 | Consumer uses getattr with different default than schema | Direct attribute access, no getattr on typed config | Grep-based CI: no `getattr(config` in core/pipeline/ |
| **Implicit default** | V20/V27/V31: llm.py silent fallbacks on exception | try/except around get_config() returns hardcoded values | Remove try/except; crash if config unavailable | No `except` blocks that return config-like values |
| **Schema duplication** | `_KNOWN_EXEC_FIELDS` manually maintained, diverges from ExecutionConfig dataclass fields | Allow-list is a second schema definition maintained by hand | Auto-derive known-keys from dataclass `__dataclass_fields__` | No manual `_KNOWN_*_FIELDS` sets anywhere |
| **Prompt metadata drift** | Template uses undeclared variable; metadata declares unused variable | Metadata and templates are hand-maintained independently | Drift detection at registry load (already exists); ensure it runs in every code path | `validate_prompts` defaults to True; smoke gate compiles all conditions |
| **Path contract break** | cases_v2.json code_files paths used as model output schema keys; storage rename changes prompt contract | Single field serves dual purpose (storage + prompt-facing) | Introduce `logical_file_keys` as stable prompt-facing contract; decouple from storage path | Validation: logical keys must not contain directory prefixes beyond case directory |
| **Divergent discovery path** | Preflight: spec_from_file_location; Execution: importlib.import_module with sys.path | Two different import mechanisms, different failure modes | Unify on file-based import in both paths | Single `_resolve_test_fn()` function used by both preflight and run_case.py |
| **Missing smoke gate** | 1,740 work items launched; all failed due to trivial import error | No end-to-end execution before fan-out | Mandatory single-case smoke test in orchestrator before dispatch | Orchestrator blocks on smoke result; failure aborts launch |
| **Launch directory gap** | Worker dir created but subprocess PYTHONPATH not validated | Directory existence ≠ environment validity | Smoke test exercises the full subprocess path | Smoke failure blocks launch |

---

## 4. Final Target Architecture

**YAML is the sole config source of truth.** Every parameter consumed by any pipeline stage exists in the YAML file. The parser crashes on missing keys. The loader crashes on unknown keys.

**Dataclasses define typed shape but not defaults.** All fields in `ExecutionConfig`, `EvaluationConfig`, `LoggingConfig` have no `= value` defaults. The parser must provide every value from YAML.

**Allow-lists are derived, not maintained.** `_KNOWN_EXEC_FIELDS` is replaced by `set(ExecutionConfig.__dataclass_fields__.keys())` minus synthetic/computed fields. No manual enumeration.

**Prompt metadata authority is enforced at load.** `validate_template_against_metadata()` runs unconditionally in production (controlled by config field `validate_prompts`, which defaults to `true` in YAML). The smoke gate compiles every condition's prompt to catch drift before fan-out.

**Prompt-facing file keys are distinct from filesystem paths.** `cases_v2.json` retains `code_files` for filesystem resolution. A new computed field `logical_file_keys` provides the stable prompt-facing contract. Generation prompts and parser output use logical keys. Storage path changes do not affect the model I/O contract.

**Preflight and execution use the same discovery mechanism.** `run_case.py` switches from `importlib.import_module()` to file-based import using `importlib.util.spec_from_file_location()`, matching `test_loader.py`. PYTHONPATH still includes `case_data_dir` for code module imports, but test discovery no longer depends on it.

**Launch gating is mandatory.** Before any multi-case or multi-worker ablation, the orchestrator runs a single-case end-to-end smoke test through the real subprocess path. Smoke failure aborts the entire launch.

---

## 5. Config Schema Redesign

### 5.1 Eliminate manual allow-lists

File: `core/config/experiment_config.py`

Replace lines 412-417:
```python
# BEFORE
_KNOWN_EXEC_FIELDS = {
    "num_workers", "worker_stagger_seconds", "token_budgets",
    "mode", "keep_eval_dirs", "subprocess_timeout",
    "worker_timeout_seconds", "worker_graceful_shutdown_seconds",
    "v3_pipeline", "validate_prompts",
}
```

With auto-derivation:
```python
# Fields that appear in YAML execution: section but map to
# nested sub-objects or are routed from other YAML sections.
_EXEC_YAML_SPECIAL = {"token_budgets", "v3_pipeline"}

def _known_yaml_keys_for(dataclass_type, specials=frozenset()):
    """Derive the set of valid YAML keys from a dataclass type.
    
    Includes dataclass field names minus internal/computed fields,
    plus any special keys that exist in YAML but are parsed into
    sub-objects or routed from other sections.
    """
    fields = set(dataclass_type.__dataclass_fields__.keys())
    # Remove fields populated from other YAML sections or computed
    internal = {f for f in fields if f.startswith("_")}
    return (fields - internal) | specials
```

Usage in `_parse_config()`:
```python
_known_exec = _known_yaml_keys_for(ExecutionConfig, _EXEC_YAML_SPECIAL)
# Remove fields populated from non-execution YAML sections
_known_exec -= {"import_summary", "file_ordering", "output_format"}
unknown = set(exec_raw.keys()) - _known_exec
if unknown:
    raise ValueError(f"Unknown fields in execution config: {unknown}")
```

Apply the same pattern for evaluation, logging, and models sections. Each section's known-key set is derived from its dataclass. Adding a field to the dataclass automatically updates the allow-list.

### 5.2 Dataclass fields have no defaults

Remove all `= value` defaults from `ExecutionConfig`, `EvaluationConfig`, `LoggingConfig`. The Python `@dataclass` constructor will raise `TypeError: __init__() missing required argument` if the parser fails to provide any field. This is a second line of defense behind `_require()`.

`RetryConfig` retains defaults because it participates in hierarchical merge (condition-specific overrides fall through to `retry_defaults`). The `retry_defaults` section itself is parsed with `_require()`.

`ModelSpec` and `EvaluatorModelSpec` retain `temperature` and `max_tokens` defaults because per-model YAML entries may omit them when the default (0.0, 128000) is correct. These are the ONLY dataclasses with defaults. Document this exception in a code comment.

### 5.3 Schema bijection check

Add to `_validate()`:
```python
def _check_schema_bijection(exec_raw, eval_raw, log_raw):
    """Verify YAML sections and dataclass fields are in bijection.
    
    Every YAML key must map to a dataclass field.
    Every dataclass field must be populated from YAML.
    """
    # Already enforced by:
    # 1. _require() crashes on missing YAML key
    # 2. No-default dataclass crashes on missing field
    # 3. unknown-key detection crashes on extra YAML key
    # This function is the runtime assertion combining all three.
    pass  # Enforcement is structural, not a runtime check
```

The bijection is enforced structurally: unknown keys crash (unknown-key detection), missing keys crash (`_require()`), unpopulated fields crash (no-default dataclass). No runtime bijection check needed — the three mechanisms compose.

---

## 6. Prompt Metadata and Template Contract Repair

### 6.1 Current state

The prompt system has strong drift detection:
- `validate_template_against_metadata()` catches undeclared template variables and unreferenced metadata declarations
- `validate_control_inputs()` catches unused control inputs
- Both run at registry load when `validate_prompts=True`

The gap: conditional-group variables (e.g., grounded-mode `ground_truth_failure_mode`) are only checked when the condition expression evaluates to true at compile time. If the smoke test does not exercise grounded mode, the drift in grounded-mode variables is not caught.

### 6.2 Fix

**Metadata remains hand-maintained and authoritative.** AST extraction is used only for drift detection. This is the correct design — metadata expresses intent, AST verifies consistency.

**Enforcement model:**

1. **At registry load** (`validate=True`): `validate_template_against_metadata()` and `validate_control_inputs()` run for every component. This catches unconditional drift.

2. **At smoke gate** (new): the smoke gate compiles every condition defined in the config. For classifier templates, it compiles once in blind mode and once in grounded mode (with synthetic ground-truth variables). This ensures conditional-group drift is caught before fan-out.

3. **Source of truth:** `core/prompts/component_metadata.yaml`

4. **Generation flow:** New components start with `generate_metadata_from_ast()` (already exists in `metadata.py:227-255`) then are manually reviewed and committed.

5. **Failure mode:** Any drift raises an exception at registry load time. The system never starts with drifted metadata.

6. **Launch gate interaction:** The smoke gate calls `_get_compiler_registry()` which triggers `registry.load(validate=True)`. If metadata has drifted, the smoke gate fails, and the launch is aborted.

### 6.3 Smoke gate classifier compilation

Add to the smoke gate sequence (Section 9):

```python
# Compile classifier in both modes to catch conditional drift
for mode in ["blind", "grounded"]:
    test_vars = {
        "task": "test", "root_cause": "test", "fix_strategy": "test",
        "code": "test", "failure_types": "test",
        "classifier_mode": mode,
    }
    if mode == "grounded":
        test_vars.update({
            "ground_truth_failure_mode": "test",
            "ground_truth_trap": "test",
            "ground_truth_invariant": "test",
        })
    _compile_prompt((config.evaluation.classifier_template,), test_vars)
```

---

## 7. Path Authority and Prompt Contract Repair

### 7.1 The problem

`cases_v2.json` stores:
```json
"code_files": ["case_data/code_snippets_v2/alias_config_b/app.py", ...]
```

These paths serve three purposes:
1. **Filesystem:** `runner.py` loads content from `PROJECT_ROOT / code_files[i]`
2. **Prompt-facing key:** The prompt shows `"case_data/code_snippets_v2/alias_config_b/app.py": "<content>"` to the model
3. **Output schema key:** The model's JSON response uses these paths as keys; the parser matches them

If `cases_v2.json` paths change (e.g., prepending `case_data/`), the prompt contract changes, old model outputs become unparseable, and analysis scripts that key on paths break.

### 7.2 Fix: Logical file keys

**In `runner.py:load_cases()`**, after loading `code_files_contents`, compute stable logical keys:

```python
# Logical file keys: <case_dir>/<filename> — stable prompt-facing contract
# Example: "alias_config_b/app.py" (not "case_data/code_snippets_v2/alias_config_b/app.py")
logical_keys = {}
for rel_path, content in code_files_contents.items():
    parts = Path(rel_path).parts
    # Find the case directory (parent of the .py file)
    case_dir = parts[-2]  # e.g., "alias_config_b"
    filename = parts[-1]   # e.g., "app.py"
    logical_key = f"{case_dir}/{filename}"
    logical_keys[logical_key] = content

case["logical_file_keys"] = logical_keys
```

**In `execution_v2.py:_render_generation_prompt()`**, use `logical_file_keys` instead of `code_files_contents`:

```python
# BEFORE
code_files = case["code_files_contents"]
# AFTER
code_files = case["logical_file_keys"]
```

**In the parser and reconstructor**, match against logical keys. In `exec_canonical.py:_materialize_package()`, map logical keys back to filesystem via `code_files_contents`.

**In `cases_v2.json`**, the `code_files` field remains the filesystem path. It is never shown to the model. The model sees only logical keys.

### 7.3 Centralized path mapping

`runner.py:load_cases()` is the single place where filesystem paths are resolved and logical keys are computed. No other code derives prompt-facing keys from `code_files` paths.

**Validation:** Assert that no logical key contains a path prefix longer than `case_dir/filename`:
```python
for lk in logical_keys:
    assert lk.count("/") == 1, f"Logical key must be case_dir/filename, got: {lk}"
```

---

## 8. Unified Test Discovery and Execution Path

### 8.1 Current divergence

| Aspect | Preflight (test_loader.py) | Execution (run_case.py) |
|---|---|---|
| Mechanism | `spec_from_file_location(name, path)` | `importlib.import_module("tests_v2.test_{family}")` |
| sys.path needed | No | Yes (lines 152-156) |
| Discovery path | `TESTS_V2_DIR / f"test_{family}.py"` | `case_data_dir` on PYTHONPATH |
| Failure if sys.path wrong | Succeeds anyway | Fails with ImportError |

### 8.2 Fix: Unify on file-based import

`run_case.py` will use `importlib.util.spec_from_file_location()` for test discovery, matching `test_loader.py`. The PYTHONPATH / sys.path injection remains for code module imports (the `pkg/` directory), but test discovery becomes path-based, not package-based.

**Changes to `core/harness/run_case.py`** (lines 151-169):

Replace:
```python
if project_root not in sys.path:
    sys.path.insert(0, project_root)
case_data_dir = os.path.join(project_root, "case_data")
if case_data_dir not in sys.path:
    sys.path.insert(0, case_data_dir)

test_fn = None
test_fn_name = None
for func_name in [f"test_{difficulty}", "test", "test_a"]:
    try:
        test_mod = importlib.import_module(f"tests_v2.test_{family}")
        fn = getattr(test_mod, func_name, None)
        if fn is not None:
            test_fn = fn
            test_fn_name = func_name
            break
    except ImportError:
        pass
```

With:
```python
import importlib.util as _ilu

tests_dir = os.path.join(project_root, "case_data", "tests_v2")
test_path = os.path.join(tests_dir, f"test_{family}.py")

if not os.path.exists(test_path):
    result["error_type"] = "TestResolutionError"
    result["error_message"] = f"Test file not found: {test_path}"
    result["execution_time_ms"] = int((time.monotonic() - t0) * 1000)
    print(json.dumps(result))
    return

spec = _ilu.spec_from_file_location(f"_t3_test_{family}", test_path)
test_mod = _ilu.module_from_spec(spec)
spec.loader.exec_module(test_mod)

test_fn = None
test_fn_name = None
for func_name in [f"test_{difficulty}", "test", "test_a"]:
    fn = getattr(test_mod, func_name, None)
    if fn is not None:
        test_fn = fn
        test_fn_name = func_name
        break
```

The sys.path injection for `project_root` and `case_data_dir` is removed from the test discovery section. PYTHONPATH (set by `exec_canonical.py` line 133) still provides `pkg_path` for code module imports — that is correct and unchanged.

### 8.3 Congruence guarantee

After this change, both preflight (`test_loader.py:_load_v2_test`) and execution (`run_case.py`) use `spec_from_file_location` with a path derived from `project_root + "case_data/tests_v2/test_{family}.py"`. If one succeeds, the other succeeds. If the test file is missing, both fail with the same error.

---

## 9. Launch Gate and Smoke Test Protocol

### 9.1 Mandatory launch gate sequence

Before any multi-case or multi-worker dispatch, the orchestrator runs these checks in order. Each check must pass before proceeding to the next. Any failure aborts the launch.

**Gate 1: Config load and validation**
- `load_config(path)` runs `_parse_config()` with `_require()` strict extraction
- `_validate(config)` runs structural checks
- Unknown-key detection rejects typos
- Already exists; enhanced by V2 strict parsing

**Gate 2: Asset preflight**
- `validate_startup(config)` checks canonical paths exist and run_dir is writable
- Already exists in `preflight.py`

**Gate 3: Prompt compilation validation**
- For every condition in `config.conditions`:
  - Compile the generation prompt with synthetic variables
  - Compile the classifier prompt in blind mode
  - If `config.evaluation.classifier_mode == "grounded"`, also compile in grounded mode
- Catches: missing templates, undeclared variables, metadata drift, section mismatch
- This replaces the implicit "first case discovers broken prompts" pattern

**Gate 4: Test discovery validation**
- `preflight_verify_tests(cases)` verifies every case has a resolvable test function
- Already exists; uses file-based import (congruent with execution after Section 8 fix)

**Gate 5: Single-case end-to-end smoke test**
- Select one case (first case in the work item list)
- Run it through the full pipeline: prompt → model call (mock if no API key) → parse → reconstruct → execute (subprocess) → classify → log
- This exercises: prompt compilation, config propagation, subprocess materialization, PYTHONPATH setup, test discovery in subprocess, result parsing
- If this fails, the launch is aborted
- The smoke test uses mock model if no API key is available, which still exercises the entire mechanical pipeline

**Gate 6: Run directory and manifest creation**
- Create run_dir with `mkdir(parents=True, exist_ok=True)`
- Write initial manifest
- Verify manifest is readable after write
- Already exists; no change needed

**Gate 7 (conditional): Retry smoke test**
- If any condition in the launch set has `retry.enabled=True`:
  - Run one case through `run_retry_v2()` for one retry condition
  - Verify retry loop reads `config.conditions[condition].retry.max_attempts` (not a module constant)
- This catches: shadow overrides of retry params, broken critique prompt compilation

### 9.2 Implementation

Add `_smoke_gate(config, cases, run_dir)` to `orchestrate.py`, called from `_run_experiment_inner()` after preflight and before work item dispatch:

```python
def _smoke_gate(config, cases, run_dir):
    """Mandatory end-to-end smoke test before fan-out.
    
    Aborts launch on any failure. Not optional. Not skippable.
    """
    print("SMOKE GATE: running pre-launch validation...", flush=True)
    
    # Gate 3: Prompt compilation
    _smoke_compile_all_prompts(config)
    
    # Gate 5: Single-case E2E
    _smoke_execute_one_case(config, cases, run_dir)
    
    # Gate 7: Retry smoke (conditional)
    retry_conditions = [c for c, cfg in config.conditions.items() if cfg.retry.enabled]
    if retry_conditions:
        _smoke_retry_one_case(config, cases, run_dir, retry_conditions[0])
    
    print("SMOKE GATE: all checks passed", flush=True)
```

---

## 10. Logging and Observability Requirements

Every config-sensitive behavioral decision must be logged in the case-end event or run-start event so post-hoc analysis can reconstruct what actually happened.

| Parameter | Where Logged | Log Field |
|---|---|---|
| retry max_attempts (effective) | retry_v2.py trajectory | `retry.max_attempts_configured` |
| retry max_total_seconds (effective) | retry_v2.py trajectory | `retry.max_total_seconds_configured` |
| subprocess timeout (effective) | exec_canonical.py result | Already in `timeout_seconds` on timeout |
| recovery execution enabled | execution_v2.py reconstruction section | `recovery_execution_enabled` |
| validate_prompts | runner.py run-start event | `config.validate_prompts` |
| classifier_mode | execution_v2.py classification section | Already logged |
| classifier_template | execution_v2.py classification section | Add `classifier_template` field |
| classifier_schema_variant | execution_v2.py classification section | Add `classifier_schema_variant` field |
| test discovery mechanism | run_case.py execution_trace | Already in trace as `test_fn: {name}` |
| resolved run directory | runner.py run-start event | Already logged |
| logical file keys | execution_v2.py prompt_meta | Add `logical_file_keys` list |
| anthropic_max_output_tokens | llm.py (on anthropic call) | Add to call log |
| anthropic_client_timeout | llm.py (on anthropic call) | Add to call log |

Implementation: each "Add" field is a one-line addition to the relevant log dict.

---

## 11. File-by-File Remediation Plan

### 11.1 `core/config/experiment_config.py`

**Responsibility:** Config schema definition, YAML parsing, validation, singleton access.

**Changes:**
- Add `_require()` and `_require_section()` helpers
- Add `_known_yaml_keys_for()` auto-derivation function
- Delete `_KNOWN_EXEC_FIELDS` manual set (lines 412-417)
- Replace all `.get("key", default)` in `_parse_config()` with `_require()`
- Remove defaults from `ExecutionConfig` fields (except `token_budgets` which uses `field(default_factory=...)` — replaced by required parsing)
- Remove defaults from `EvaluationConfig` fields
- Remove defaults from `LoggingConfig` fields
- Delete `store_raw_prompts` and `store_raw_outputs` from `LoggingConfig` (dead)
- Add `recovery_execution: bool`, `max_orchestrator_attempts: int`, `anthropic_client_timeout: float`, `anthropic_max_output_tokens: int` to `ExecutionConfig`
- Change `ModelsConfig.no_temperature_prefixes` from hardcoded property to `tuple[str, ...]` field
- Add unknown-key detection for evaluation, logging, logging.redis, models sections using `_known_yaml_keys_for()`
- Update `config_to_dict()` for new fields
- Update `_validate()` for new fields

### 11.2 `core/config/config_storage/default.yaml`

**Responsibility:** Canonical default values for every parameter.

**Changes:**
- Add to `execution:`: `worker_stagger_seconds`, `subprocess_timeout`, `worker_timeout_seconds`, `worker_graceful_shutdown_seconds`, `mode`, `keep_eval_dirs`, `validate_prompts`, `recovery_execution`, `max_orchestrator_attempts`, `anthropic_client_timeout`, `anthropic_max_output_tokens`
- Add to `evaluation:`: `classifier_mode`, `reasoning_correct_mode`, `classifier_template`, `classifier_schema_variant`, `generation_schema_variant`
- Remove from `evaluation:`: `subprocess_timeout` (misplaced, V3)
- Add to `models:`: `no_temperature_prefixes`
- Remove from `logging.store:`: `generated_code`, `execution_traces`, `raw_prompts`, `raw_outputs`
- Remove entire `logging.store:` sub-section

### 11.3 Per-experiment YAML configs (102 files in `core/config/config_storage/`)

**Responsibility:** Per-experiment overrides of default values.

**Changes:** Write `scripts/migrate_yaml_configs.py` that:
1. Reads each YAML
2. Adds missing required fields with canonical values
3. Removes deleted fields (`logging.store.*`, `evaluation.subprocess_timeout`)
4. Writes back
5. Reports changes

### 11.4 `core/pipeline/orchestration/retry_v2.py`

**Responsibility:** Multi-attempt retry execution.

**Changes:**
- Delete `MAX_ITERATIONS = 3` (line 71)
- Delete `MAX_TOTAL_SECONDS = 300` (line 72)
- In `run_retry_v2()`: read `max_iterations` and `max_total_seconds` from `config.conditions[condition].retry`
- Replace all references to `MAX_ITERATIONS` (lines 357, 468) and `MAX_TOTAL_SECONDS` (line 359)
- Log effective retry params: add `retry.max_attempts_configured` and `retry.max_total_seconds_configured` to trajectory

### 11.5 `core/pipeline/orchestration/orchestrate.py`

**Responsibility:** Multi-worker orchestration and worker lifecycle.

**Changes:**
- Delete `MAX_ATTEMPTS = 10` (line 225)
- Replace `getattr(config.execution, "num_workers", 4)` (line 1115) with `config.execution.num_workers`
- Replace `getattr(config.execution, "worker_timeout_seconds", 600)` (line 1116) with `config.execution.worker_timeout_seconds`
- Replace `getattr(config.execution, "worker_graceful_shutdown_seconds", 30)` (line 1117) with `config.execution.worker_graceful_shutdown_seconds`
- Replace `MAX_ATTEMPTS` references (lines 1146, 1149) with `config.execution.max_orchestrator_attempts`
- Add `_SIGKILL_WAIT_SECONDS = 5` constant with comment: infrastructure constant, not experimental config
- Add `_smoke_gate()` function, called from `_run_experiment_inner()` before dispatch loop

### 11.6 `core/pipeline/orchestration/execution_v2.py`

**Responsibility:** Canonical single-case execution pipeline.

**Changes:**
- Delete `_ENABLE_RECOVERY_EXECUTION = True` (line 37)
- Replace reference in `_select_artifact()` (line 242) with `get_config().execution.recovery_execution`
- In `_build_reconstruction_section()`: add `recovery_execution_enabled` field
- In `_render_generation_prompt()`: use `case["logical_file_keys"]` instead of `case["code_files_contents"]`
- In classification section: add `classifier_template` and `classifier_schema_variant` fields

### 11.7 `core/pipeline/execution/exec_canonical.py`

**Responsibility:** Disk-backed subprocess execution.

**Changes:**
- Replace lines 299-302 (hasattr subprocess_timeout pattern) with `timeout = config.execution.subprocess_timeout`
- Replace lines 337-339 and 353-355 (hasattr keep_eval_dirs pattern) with `keep = config.execution.keep_eval_dirs`
- Remove default parameter from `_run_subprocess(pkg_dir, project_root, timeout=30)` signature — `timeout` becomes required positional

### 11.8 `core/pipeline/orchestration/runner.py`

**Responsibility:** Standalone runner and case loading.

**Changes:**
- In `load_cases()`: after loading `code_files_contents`, compute `logical_file_keys` per case
- Add assertion that logical keys have exactly one `/` (case_dir/filename)
- Pass `logical_file_keys` through to execution

### 11.9 `core/harness/run_case.py`

**Responsibility:** Subprocess harness for test execution.

**Changes:**
- Replace package-based test import (lines 151-169) with file-based import using `spec_from_file_location()`
- Remove `sys.path.insert(0, project_root)` and `sys.path.insert(0, case_data_dir)` for test discovery
- PYTHONPATH (set by exec_canonical.py) remains for `pkg/` module imports — that is unchanged

### 11.10 `core/pipeline/llm.py`

**Responsibility:** LLM API calls.

**Changes:**
- Delete `_get_output_format()` (dead function, lines 30-37)
- Delete `get_model_config()` (dead function, lines 147-161)
- Rewrite `_get_model_spec()`: remove silent fallback, crash on unknown model
- Rewrite `_get_anthropic_max_tokens()`: use `config.execution.anthropic_max_output_tokens` as cap
- Replace `timeout=120.0` in `_anthropic_call()` with `get_config().execution.anthropic_client_timeout`
- Replace `no_temp` fallback in `_openai_call()` with direct `get_config().models.no_temperature_prefixes`
- Log `anthropic_max_output_tokens` and `anthropic_client_timeout` in call records

### 11.11 Prompt metadata files

**Files:** `core/prompts/component_metadata.yaml`, `core/prompts/prompt_manifest.yaml`

**Changes:** No structural changes. The existing drift detection is sufficient. The smoke gate (Section 9) exercises all conditions and both classifier modes, catching any drift before fan-out.

### 11.12 `scripts/audit_config_usage.py`

**Responsibility:** CI-level enforcement of config hygiene.

**Changes:**
- Add check: no `.get("key", <literal>)` in `_parse_config()` function
- Add check: no `getattr(config` in `core/pipeline/`
- Add check: no `hasattr(config` in `core/pipeline/` (excluding `preflight.py`)
- Add check: no `MAX_` module constants in `core/pipeline/orchestration/` (excluding `_SIGKILL_WAIT_SECONDS`)
- Add check: no `_KNOWN_*_FIELDS` manual sets in `experiment_config.py`
- Add check: every `ExecutionConfig` field (minus computed) accessed somewhere in `core/pipeline/`

---

## 12. Enforcement Mechanisms

### 12.1 Static enforcement

- **No-default dataclasses:** `ExecutionConfig`, `EvaluationConfig`, `LoggingConfig` fields have no `= value`. Python raises `TypeError` if parser fails to set any field.
- **Auto-derived allow-lists:** `_known_yaml_keys_for(DataclassType)` eliminates manual `_KNOWN_*_FIELDS` sets. Adding a field to the dataclass automatically updates the allowed YAML key set.
- **`_require()` extraction:** Every `.get("key", default)` in `_parse_config()` replaced by `_require()`. Missing YAML key raises `ValueError`.

### 12.2 Runtime enforcement

- **Unknown-key detection:** Every section in `_parse_config()` computes `unknown = yaml_keys - known_keys`. Non-empty raises `ValueError`.
- **`get_config()` crash:** Accessing config before loading raises `RuntimeError`.
- **Smoke gate abort:** `_smoke_gate()` raises `RuntimeError` on any failure, blocking fan-out.
- **Partition assertion:** `_compute_evaluation()` asserts outcome class partition integrity.

### 12.3 Audit tooling

- **`scripts/audit_config_usage.py`:** Scans for forbidden patterns (`.get` defaults in parser, `getattr` on config, `hasattr` on config, dead functions, manual allow-lists, module constants). Exit code 1 on violation.
- **Prompt drift detection:** Registry load with `validate=True` catches template/metadata mismatch.
- **Logical key validation:** Assertion in `load_cases()` that logical keys match `case_dir/filename` pattern.

### 12.4 CI/pre-commit gates

- `scripts/audit_config_usage.py` runs on every commit touching `core/`
- `scripts/check_forbidden_paths.py` (already exists) runs on every commit

---

## 13. Ordered Migration Plan

### Step 1: Add helpers and infrastructure

Files: `experiment_config.py`
- Add `_require()`, `_require_section()`, `_known_yaml_keys_for()`
- No behavioral change yet — these are additive

### Step 2: Update default.yaml with all missing fields

File: `default.yaml`
- Add all missing execution, evaluation, models fields
- Remove misplaced `evaluation.subprocess_timeout`
- Remove dead `logging.store` fields
- After this step, default.yaml is complete

### Step 3: Write and run YAML migration script

File: `scripts/migrate_yaml_configs.py`
- Update all 102 per-experiment YAMLs
- Add missing fields, remove deleted fields

### Step 4: Switch parser to strict extraction

File: `experiment_config.py`
- Replace all `.get("key", default)` with `_require()` in `_parse_config()`
- Replace manual `_KNOWN_EXEC_FIELDS` with auto-derived sets
- Remove defaults from dataclass fields
- Add unknown-key detection for all sections
- Verify: `load_config("core/config/config_storage/default.yaml")` succeeds

### Step 5: Add new config fields to dataclasses

File: `experiment_config.py`
- Add `recovery_execution`, `max_orchestrator_attempts`, `anthropic_client_timeout`, `anthropic_max_output_tokens` to `ExecutionConfig`
- Change `ModelsConfig.no_temperature_prefixes` to field
- Delete dead fields from `LoggingConfig`
- Update `config_to_dict()`

### Step 6: Rewire consumers — config-only changes

Files: `retry_v2.py`, `orchestrate.py`, `exec_canonical.py`, `execution_v2.py`, `llm.py`
- Delete module constants
- Replace getattr/hasattr with direct access
- Read retry params from config
- Read new config fields
- Delete dead functions from llm.py

### Step 7: Compute logical file keys

File: `runner.py`
- Add `logical_file_keys` computation in `load_cases()`
- Update `execution_v2.py` to use logical keys for prompt generation

### Step 8: Unify test discovery

File: `run_case.py`
- Replace `importlib.import_module()` test discovery with `spec_from_file_location()`
- Remove sys.path injection for project_root/case_data_dir in test discovery section

### Step 9: Add smoke gate

File: `orchestrate.py`
- Add `_smoke_gate()` function
- Call from `_run_experiment_inner()` between preflight and dispatch
- Implement Gates 3, 5, and 7

### Step 10: Add logging fields

Files: `retry_v2.py`, `execution_v2.py`, `llm.py`
- Log effective retry params in trajectory
- Log classifier_template and schema_variant in classification section
- Log recovery_execution_enabled in reconstruction section
- Log anthropic config in call records

### Step 11: Update audit script

File: `scripts/audit_config_usage.py`
- Add all new checks (manual allow-lists, module constants, getattr patterns)

### Step 12: Validate

- Run all validation criteria from Section 14

---

## 14. Validation Matrix

| # | Check | Command / Method | Pass Criterion |
|---|---|---|---|
| 1 | All test cases pass | `.venv/bin/python scripts/test_case.py --all --ref` | 58/58 PASS |
| 2 | Config loads cleanly | `python -c "from core.config.experiment_config import load_config; load_config('core/config/config_storage/default.yaml')"` | No error |
| 3 | Missing YAML key crashes | Remove `execution.subprocess_timeout` from default.yaml, load config | `ValueError: CONFIG ERROR: execution.subprocess_timeout is REQUIRED` |
| 4 | Unknown YAML key crashes | Add `execution.bogus_field: 42` to default.yaml, load config | `ValueError: Unknown fields in execution config: {'bogus_field'}` |
| 5 | No manual allow-lists | `grep -n "_KNOWN_.*_FIELDS" core/config/experiment_config.py` | Zero matches |
| 6 | No getattr on config | `grep -rn "getattr(config" core/pipeline/` | Zero matches |
| 7 | No hasattr on config | `grep -rn "hasattr(config" core/pipeline/` | Zero matches (excluding preflight.py) |
| 8 | No .get defaults in parser | `grep -n "\.get(" core/config/experiment_config.py` in `_parse_config` scope | Zero `.get("key", <literal>)` patterns |
| 9 | No module constants | `grep -n "^MAX_" core/pipeline/orchestration/retry_v2.py core/pipeline/orchestration/orchestrate.py` | Zero matches |
| 10 | Dead code removed | `grep -n "_get_output_format\|get_model_config" core/pipeline/llm.py` | Zero matches |
| 11 | Retry reads config | Change `retry_defaults.max_attempts: 2` in YAML, run retry condition, check trajectory | Exactly 2 iterations |
| 12 | Subprocess timeout reads config | Set `execution.subprocess_timeout: 1`, run a case | TIMEOUT result |
| 13 | Recovery flag reads config | Set `execution.recovery_execution: false`, verify routing | `selected_source: "none"` for recovery-only cases |
| 14 | Prompt compilation smoke | Smoke gate compiles all conditions | No compilation errors |
| 15 | Classifier grounded-mode smoke | Smoke gate compiles classifier in grounded mode | No missing-variable errors |
| 16 | Test discovery congruence | Preflight passes AND subprocess test resolution succeeds for same case | Both succeed or both fail |
| 17 | Logical file keys stable | Change `cases_v2.json` code_files prefix, verify logical keys unchanged | Logical keys match `case_dir/filename` |
| 18 | Audit script clean | `.venv/bin/python scripts/audit_config_usage.py` | Exit code 0 |
| 19 | E2E single case | Run orchestrator with 1 case, 1 condition, 1 trial | PASS or expected FAIL (not ERROR) |
| 20 | E2E retry case | Run orchestrator with 1 retry condition | Trajectory shows config max_attempts |
| 21 | E2E multi-case launch | Run orchestrator with 5 cases, 1 condition | All 5 complete without infra errors |

---

## 15. Explicit Closure of Audit Findings

### Forensic Config Audit V1

| ID | Violation | Resolution |
|---|---|---|
| V1 | retry MAX_ITERATIONS shadows config | Fixed: delete constant, read config.conditions[cond].retry.max_attempts (Step 6) |
| V2 | retry MAX_TOTAL_SECONDS shadows config | Fixed: delete constant, read config.conditions[cond].retry.max_total_seconds (Step 6) |
| V3 | evaluation.subprocess_timeout silently dropped | Fixed: remove from evaluation section, add to execution section (Step 2) |
| V4 | execution.subprocess_timeout Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V5 | execution.worker_timeout_seconds Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V6 | execution.worker_graceful_shutdown_seconds Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V7 | execution.worker_stagger_seconds Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V8 | execution.mode Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V9 | execution.keep_eval_dirs Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V10 | execution.validate_prompts Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V11 | evaluation.classifier_mode Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V12 | evaluation.reasoning_correct_mode Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V13 | evaluation.classifier_template Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V14 | evaluation.classifier_schema_variant Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V15 | evaluation.generation_schema_variant Python-only | Fixed: add to default.yaml, strict parse (Steps 2, 4) |
| V16 | orchestrator MAX_ATTEMPTS Python-only | Fixed: add to config as execution.max_orchestrator_attempts (Steps 2, 5, 6) |
| V17 | _ENABLE_RECOVERY_EXECUTION Python-only | Fixed: add to config as execution.recovery_execution (Steps 2, 5, 6) |
| V18 | anthropic client timeout Python-only | Fixed: add to config as execution.anthropic_client_timeout (Steps 2, 5, 6) |
| V19 | anthropic max_tokens cap Python-only | Fixed: add to config as execution.anthropic_max_output_tokens (Steps 2, 5, 6) |
| V20 | anthropic fallback max_tokens implicit | Fixed: _get_anthropic_max_tokens reads config cap, no silent fallback (Step 6) |
| V21 | no_temperature_prefixes hardcoded | Fixed: move to config as models.no_temperature_prefixes (Steps 2, 5, 6) |
| V22 | logging.store.generated_code silently dropped | Fixed: remove from YAML, add unknown-key detection (Steps 2, 4) |
| V23 | logging.store.execution_traces silently dropped | Fixed: remove from YAML, add unknown-key detection (Steps 2, 4) |
| V24 | store_raw_prompts dead config | Fixed: delete from dataclass and parser (Step 5) |
| V25 | store_raw_outputs dead config | Fixed: delete from dataclass and parser (Step 5) |
| V26 | getattr num_workers divergent fallback | Fixed: direct attribute access, no getattr (Step 6) |
| V27 | _get_model_spec silent fallback | Fixed: crash on unknown model, no silent (0.0, 1.0) (Step 6) |
| V28 | _get_output_format dead function | Fixed: delete function (Step 6) |
| V29 | get_model_config dead function | Fixed: delete function (Step 6) |
| V30 | orchestrate.py process wait timeouts | Fixed: rename to _SIGKILL_WAIT_SECONDS with comment (Step 6) |
| V31 | llm.py no_temp fallback | Fixed: direct config access, no fallback (Step 6) |

### V3 Ablation Launch Issues (referenced in revision prompt)

| Issue | Description | Resolution |
|---|---|---|
| 1 | `validate_prompts` added to config but `_KNOWN_EXEC_FIELDS` not updated | Fixed: eliminate manual allow-lists, auto-derive from dataclass (Step 4) |
| 2 | Undeclared grounded-mode template variables | Fixed: smoke gate compiles classifier in both blind and grounded modes (Step 9) |
| 3 | Declared-but-unused metadata variable `risk_check` | Fixed: existing drift detection catches this at registry load; smoke gate exercises all conditions (Step 9) |
| 4 | `import os` missing from run_case.py | Fixed: smoke gate runs single-case E2E through real subprocess before fan-out (Step 9) |
| 5 | cases_v2.json path prefix change breaks prompt contract | Fixed: logical_file_keys decoupled from storage paths (Step 7) |
| 6 | Preflight uses file-based import, execution uses package-based import | Fixed: execution switches to file-based import, both congruent (Step 8) |
| 7 | Worker directory / manifest write failure | Fixed: smoke gate exercises full subprocess path including directory creation (Step 9) |

**All items closed. No open issues.**
