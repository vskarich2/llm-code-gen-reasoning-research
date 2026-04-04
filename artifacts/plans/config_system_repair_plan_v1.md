# Config System Repair Plan v1

Reference: `artifacts/plans/config_forensic_audit_v1.md` (31 violations, 67 parameters, 29.9% not YAML-controlled)

---

## SECTION 1 — ROOT CAUSE ANALYSIS

Three architectural mistakes created this:

**1. Permissive parser.** `_parse_config()` uses `.get(key, default)` for every field. This means any YAML key can be omitted and the system silently falls back to a Python literal. The parser was designed for developer convenience, not for scientific reproducibility. The correct design: crash on missing keys.

**2. No contract between YAML schema and Python dataclasses.** The `ExecutionConfig` dataclass defines 12 fields with defaults. The `default.yaml` defines 5 of them. There is no mechanism that verifies the two are aligned. Fields can exist in one and not the other, and no error fires.

**3. Module-level constants as config.** `retry_v2.py`, `orchestrate.py`, and `execution_v2.py` define module-level constants (`MAX_ITERATIONS`, `MAX_TOTAL_SECONDS`, `MAX_ATTEMPTS`, `_ENABLE_RECOVERY_EXECUTION`) that shadow or bypass the config system. These were written before the config system existed and were never migrated.

---

## SECTION 2 — TARGET ARCHITECTURE

After this repair:

**Config is defined** in exactly one place: YAML files under `core/config/config_storage/`. The file `default.yaml` contains every parameter the system uses. No parameter is absent from `default.yaml`.

**Config is loaded** by `load_config()` in `experiment_config.py`. The parser uses `_require()` for every field extraction. If a YAML file omits a field, the system crashes with a message naming the missing field and section. There are zero `.get(key, default)` calls in `_parse_config()`.

**Config is accessed** via `get_config()` returning typed dataclasses. All consumer code reads attributes directly (`config.execution.subprocess_timeout`). There are zero `getattr(config.X, "Y", fallback)` or `hasattr(config.X, "Y")` patterns. There are zero module-level constants that duplicate config values.

**What is forbidden:**
- `.get("key", literal)` in `_parse_config()` — use `_require()` instead
- `getattr(config.*, "field", fallback)` — use direct attribute access
- `hasattr(config.*, "field")` — config is typed; fields always exist
- Module-level constants for values that belong in config
- `try/except` around `get_config()` that returns a fallback value
- YAML keys that are not extracted by the parser (validated at load time)

---

## SECTION 3 — FULL VIOLATION ELIMINATION

### 3.1 SHADOW_OVERRIDE (V1, V2)

**V1 + V2: retry_v2.py MAX_ITERATIONS and MAX_TOTAL_SECONDS**

File: `core/pipeline/orchestration/retry_v2.py`

Delete lines 71-72:
```
MAX_ITERATIONS = 3
MAX_TOTAL_SECONDS = 300
```

In `run_retry_v2()` (line 327 onward), after `config = get_config()`, add:
```python
cond_retry = config.conditions[condition].retry
max_iterations = cond_retry.max_attempts
max_total_seconds = cond_retry.max_total_seconds
```

Replace line 357:
```python
# BEFORE
for k in range(MAX_ITERATIONS):
# AFTER
for k in range(max_iterations):
```

Replace line 359:
```python
# BEFORE
if elapsed > MAX_TOTAL_SECONDS:
# AFTER
if elapsed > max_total_seconds:
```

Replace line 468:
```python
# BEFORE
if not passed and k < MAX_ITERATIONS - 1:
# AFTER
if not passed and k < max_iterations - 1:
```

### 3.2 SILENT_DROP (V3, V22, V23)

**V3: subprocess_timeout in wrong YAML section**

File: `core/config/config_storage/default.yaml`

Remove `subprocess_timeout: 30` from the `evaluation:` section (line 178).
Add `subprocess_timeout: 30` to the `execution:` section. (Already handled by V4 fix below.)

**V22 + V23: logging.store.generated_code and execution_traces**

File: `core/config/config_storage/default.yaml`

Remove these two lines from default.yaml:
```yaml
    generated_code: true
    execution_traces: true
```

These fields are never parsed and never used. Delete them. Do NOT add them to LoggingConfig — they have no consumer code.

**Parser-level enforcement** (prevents future silent drops): add unknown-key detection to every section in `_parse_config()`. Model after the existing `_KNOWN_EXEC_FIELDS` check at lines 412-423.

Add to `_parse_config()` after parsing each section:

```python
# evaluation section
_KNOWN_EVAL_FIELDS = {
    "leg", "failure_classification", "alignment",
    "classifier_mode", "reasoning_correct_mode",
    "classifier_template", "classifier_schema_variant",
    "generation_schema_variant",
}
_unknown_eval = set(eval_section.keys()) - _KNOWN_EVAL_FIELDS
if _unknown_eval:
    raise ValueError(
        f"Unknown fields in evaluation config: {_unknown_eval}. "
        f"Valid fields: {sorted(_KNOWN_EVAL_FIELDS)}"
    )

# logging section
_KNOWN_LOG_FIELDS = {"level", "output_dir", "store", "redis"}
_unknown_log = set(log_raw.keys()) - _KNOWN_LOG_FIELDS
if _unknown_log:
    raise ValueError(
        f"Unknown fields in logging config: {_unknown_log}. "
        f"Valid fields: {sorted(_KNOWN_LOG_FIELDS)}"
    )

# logging.store sub-section
_KNOWN_STORE_FIELDS = {"raw_prompts", "raw_outputs"}
store_raw = log_raw.get("store", {})
_unknown_store = set(store_raw.keys()) - _KNOWN_STORE_FIELDS
if _unknown_store:
    raise ValueError(
        f"Unknown fields in logging.store config: {_unknown_store}. "
        f"Valid fields: {sorted(_KNOWN_STORE_FIELDS)}"
    )

# models section
_KNOWN_MODELS_FIELDS = {"generation", "evaluator", "failure_classifier", "no_temperature_prefixes"}
_unknown_models = set(models_raw.keys()) - _KNOWN_MODELS_FIELDS
if _unknown_models:
    raise ValueError(
        f"Unknown fields in models config: {_unknown_models}. "
        f"Valid fields: {sorted(_KNOWN_MODELS_FIELDS)}"
    )
```

### 3.3 HARDCODED_DEFAULT (V4-V10, V11-V15, V16-V19, V21)

**Strategy:** Add every missing field to `default.yaml`, then replace every `.get("key", default)` in `_parse_config()` with `_require()`.

**Step A: Add `_require()` helper to experiment_config.py**

Add after the imports (before `_parse_config`):

```python
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
```

**Step B: Update default.yaml**

File: `core/config/config_storage/default.yaml`

Add to `execution:` section (items currently absent):
```yaml
execution:
  num_workers: 1
  worker_stagger_seconds: 3
  subprocess_timeout: 30
  worker_timeout_seconds: 600
  worker_graceful_shutdown_seconds: 30
  mode: "canonical"
  keep_eval_dirs: false
  validate_prompts: true
  recovery_execution: true
  max_orchestrator_attempts: 10
  anthropic_client_timeout: 120.0
  anthropic_max_output_tokens: 8192
  token_budgets:
    "gpt-4.1-nano": 12000
    "gpt-4o-mini": 12000
    "gpt-5-mini": 16000
    "gpt-5.4-mini": 16000
    default: 10000
  v3_pipeline:
    import_summary: false
    file_ordering: "dependency"
```

Add to `evaluation:` section (items currently absent), and REMOVE `subprocess_timeout`:
```yaml
evaluation:
  leg:
    enabled: true
  failure_classification:
    enabled: true
  alignment:
    enabled: true
  classifier_mode: "blind"
  reasoning_correct_mode: "strict"
  classifier_template: "classify_reasoning_v2"
  classifier_schema_variant: "v2_semicolon"
  generation_schema_variant: "v2"
```

Add to `models:` section:
```yaml
models:
  no_temperature_prefixes: ["o1", "o3", "o4", "gpt-5"]
  generation:
    ...
```

Remove from `logging.store:`:
```yaml
  store:
    raw_prompts: true
    raw_outputs: true
    # DELETE: generated_code: true
    # DELETE: execution_traces: true
```

**Step C: Update `ExecutionConfig` dataclass**

File: `core/config/experiment_config.py`

Add new fields to `ExecutionConfig`:
```python
@dataclass
class ExecutionConfig:
    num_workers: int
    worker_stagger_seconds: int
    token_budgets: TokenBudgetConfig
    import_summary: bool
    file_ordering: str
    output_format: str
    mode: str
    keep_eval_dirs: bool
    subprocess_timeout: int
    worker_timeout_seconds: int
    validate_prompts: bool
    worker_graceful_shutdown_seconds: int
    recovery_execution: bool           # NEW — replaces _ENABLE_RECOVERY_EXECUTION
    max_orchestrator_attempts: int     # NEW — replaces orchestrate.py MAX_ATTEMPTS
    anthropic_client_timeout: float    # NEW — replaces llm.py hardcoded 120.0
    anthropic_max_output_tokens: int   # NEW — replaces llm.py hardcoded 8192
```

Remove ALL default values from the dataclass. Fields have no `= value`. This enforces that the parser must set every field from YAML.

Also update `EvaluationConfig` — remove all defaults:
```python
@dataclass
class EvaluationConfig:
    leg_enabled: bool
    failure_classification_enabled: bool
    alignment_enabled: bool
    classifier_mode: str
    reasoning_correct_mode: str
    classifier_template: str
    classifier_schema_variant: str
    generation_schema_variant: str
```

Also update `LoggingConfig` — remove all defaults, and delete `store_raw_prompts` and `store_raw_outputs` (dead config, see V24/V25):
```python
@dataclass
class LoggingConfig:
    level: str
    output_dir: str
    redis_enabled: bool
    redis_url: str
    redis_stream_maxlen: int
```

**Step D: Replace all `.get()` with `_require()` in `_parse_config()`**

Every call of the form `foo_raw.get("key", default)` becomes `_require(foo_raw, "key", "section")`.

Example replacement for execution section (lines 425-437):
```python
execution = ExecutionConfig(
    num_workers=_require(exec_raw, "num_workers", "execution"),
    worker_stagger_seconds=_require(exec_raw, "worker_stagger_seconds", "execution"),
    token_budgets=token_budgets,
    import_summary=_require(v3_raw, "import_summary", "execution.v3_pipeline"),
    file_ordering=_require(v3_raw, "file_ordering", "execution.v3_pipeline"),
    output_format=_require(_require_section(raw, "prompts"), "output_format", "prompts"),
    mode=_require(exec_raw, "mode", "execution"),
    keep_eval_dirs=_require(exec_raw, "keep_eval_dirs", "execution"),
    subprocess_timeout=_require(exec_raw, "subprocess_timeout", "execution"),
    worker_timeout_seconds=_require(exec_raw, "worker_timeout_seconds", "execution"),
    worker_graceful_shutdown_seconds=_require(exec_raw, "worker_graceful_shutdown_seconds", "execution"),
    validate_prompts=_require(exec_raw, "validate_prompts", "execution"),
    recovery_execution=_require(exec_raw, "recovery_execution", "execution"),
    max_orchestrator_attempts=_require(exec_raw, "max_orchestrator_attempts", "execution"),
    anthropic_client_timeout=_require(exec_raw, "anthropic_client_timeout", "execution"),
    anthropic_max_output_tokens=_require(exec_raw, "anthropic_max_output_tokens", "execution"),
)
```

Same pattern for evaluation (lines 387-398):
```python
evaluation = EvaluationConfig(
    leg_enabled=_require(_require_section(eval_section, "leg"), "enabled", "evaluation.leg"),
    failure_classification_enabled=_require(
        _require_section(eval_section, "failure_classification"), "enabled",
        "evaluation.failure_classification"),
    alignment_enabled=_require(_require_section(eval_section, "alignment"), "enabled", "evaluation.alignment"),
    classifier_mode=_require(eval_section, "classifier_mode", "evaluation"),
    reasoning_correct_mode=_require(eval_section, "reasoning_correct_mode", "evaluation"),
    classifier_template=_require(eval_section, "classifier_template", "evaluation"),
    classifier_schema_variant=_require(eval_section, "classifier_schema_variant", "evaluation"),
    generation_schema_variant=_require(eval_section, "generation_schema_variant", "evaluation"),
)
```

Same pattern for logging (lines 441-451):
```python
logging_config = LoggingConfig(
    level=_require(log_raw, "level", "logging"),
    output_dir=_require(log_raw, "output_dir", "logging"),
    redis_enabled=_require(redis_raw, "enabled", "logging.redis"),
    redis_url=_require(redis_raw, "url", "logging.redis"),
    redis_stream_maxlen=_require(redis_raw, "stream_maxlen", "logging.redis"),
)
```

Same pattern for models (lines 317-337). Temperature, max_tokens, top_p become required in YAML for each generation model.

**Step E: Update `ModelsConfig` for no_temperature_prefixes (V21)**

File: `core/config/experiment_config.py`

Replace the hardcoded property:
```python
# BEFORE (line 62-63)
@property
def no_temperature_prefixes(self) -> tuple[str, ...]:
    return ("o1", "o3", "o4", "gpt-5")

# AFTER
no_temperature_prefixes: tuple[str, ...]
```

In `_parse_config()`, parse it from YAML:
```python
models = ModelsConfig(
    generation=generation,
    evaluator=evaluator,
    failure_classifier_name=fc_name,
    no_temperature_prefixes=tuple(_require(models_raw, "no_temperature_prefixes", "models")),
)
```

**V16: orchestrate.py MAX_ATTEMPTS**

File: `core/pipeline/orchestration/orchestrate.py`

Delete line 225:
```
MAX_ATTEMPTS = 10
```

Replace line 1146:
```python
# BEFORE
if item.attempt > MAX_ATTEMPTS:
# AFTER
if item.attempt > config.execution.max_orchestrator_attempts:
```

Replace line 1149:
```python
# BEFORE
error=f"max attempts ({MAX_ATTEMPTS}) exceeded"
# AFTER
error=f"max attempts ({config.execution.max_orchestrator_attempts}) exceeded"
```

**V17: _ENABLE_RECOVERY_EXECUTION**

File: `core/pipeline/orchestration/execution_v2.py`

Delete line 37:
```
_ENABLE_RECOVERY_EXECUTION = True
```

In `_select_artifact()` (line 242), replace:
```python
# BEFORE
elif (_ENABLE_RECOVERY_EXECUTION
      and recovery_parse.parse_valid
      and recovery_sv.structurally_valid):

# AFTER
elif (get_config().execution.recovery_execution
      and recovery_parse.parse_valid
      and recovery_sv.structurally_valid):
```

Update docstring at line 226 accordingly.

**V18: anthropic client timeout**

File: `core/pipeline/llm.py`

Replace line 192:
```python
# BEFORE
client = anthropic.Anthropic(api_key=api_key, timeout=120.0)

# AFTER
from core.config.experiment_config import get_config
client = anthropic.Anthropic(
    api_key=api_key,
    timeout=get_config().execution.anthropic_client_timeout,
)
```

**V19: anthropic max_tokens cap**

File: `core/pipeline/llm.py`

Replace `_get_anthropic_max_tokens()` (lines 202-216):
```python
def _get_anthropic_max_tokens(model: str) -> int:
    """Get max output tokens for Anthropic models from config."""
    from core.config.experiment_config import get_config
    config = get_config()
    cap = config.execution.anthropic_max_output_tokens
    try:
        spec = config.get_generation_model(model)
        return min(spec.max_tokens, cap)
    except ValueError:
        return cap
```

**V30: orchestrate.py process wait timeouts**

File: `core/pipeline/orchestration/orchestrate.py`

Line 807: This is a `ps` command timeout for orphan PID verification. This is infrastructure, not experimental config. It stays at 5s — this is a system utility timeout, not an experiment parameter. No change.

Lines 949, 990: These are post-SIGKILL wait timeouts. After killing a process, waiting more than 5s is pointless. These are infrastructure constants, not experiment parameters. No change. BUT: rename them to make this explicit:

```python
# At module level, with comment
_SIGKILL_WAIT_SECONDS = 5  # infrastructure constant, not experiment config
```

Replace line 949: `worker.process.wait(timeout=_SIGKILL_WAIT_SECONDS)`
Replace line 990: `worker.process.wait(timeout=_SIGKILL_WAIT_SECONDS)`

### 3.4 DEAD_CONFIG (V24, V25, V28, V29)

**V24 + V25: store_raw_prompts, store_raw_outputs**

These fields are parsed from YAML into `LoggingConfig` but never read by any code.

Action: Delete them from `LoggingConfig` dataclass. Delete the corresponding lines from `_parse_config()`. Delete from default.yaml's `logging.store` section. Delete from all 102 YAML configs.

The `logging.store` section in YAML becomes empty. Remove it entirely. The `logging:` section retains `level`, `output_dir`, and `redis`.

**V28: _get_output_format() in llm.py**

File: `core/pipeline/llm.py`

Delete lines 30-37 (the entire `_get_output_format` function). Zero callers.

**V29: get_model_config() in llm.py**

File: `core/pipeline/llm.py`

Delete lines 147-161 (the entire `get_model_config` function). Zero callers.

### 3.5 DIVERGENT_SOURCE (V26)

**V26: getattr fallback mismatch in orchestrate.py**

File: `core/pipeline/orchestration/orchestrate.py`

Replace lines 1115-1117:
```python
# BEFORE
num_workers = getattr(config.execution, "num_workers", 4)
timeout_seconds = getattr(config.execution, "worker_timeout_seconds", 600)
grace_seconds = getattr(config.execution, "worker_graceful_shutdown_seconds", 30)

# AFTER
num_workers = config.execution.num_workers
timeout_seconds = config.execution.worker_timeout_seconds
grace_seconds = config.execution.worker_graceful_shutdown_seconds
```

### 3.6 IMPLICIT_DEFAULT (V20, V27, V31)

**V20: llm.py fallback max_tokens (4096)**

Eliminated by V19 fix. `_get_anthropic_max_tokens` now reads `config.execution.anthropic_max_output_tokens` as the cap and falls back to `cap` (from config) instead of hardcoded 4096.

**V27: llm.py _get_model_spec fallback (0.0, 1.0)**

File: `core/pipeline/llm.py`

Replace `_get_model_spec()` (lines 40-59):
```python
def _get_model_spec(model_name: str):
    """Get model parameters from config. Crashes if config unavailable."""
    from core.config.experiment_config import get_config
    config = get_config()
    try:
        spec = config.get_generation_model(model_name)
        return spec.temperature, spec.top_p
    except ValueError:
        # Model not in generation list — must be evaluator
        if model_name == config.models.evaluator.name:
            return config.models.evaluator.temperature, 1.0
        raise ValueError(
            f"Model '{model_name}' not found in generation models or evaluator"
        )
```

No silent fallback. If model is not in config, raise.

**V31: llm.py no_temp fallback**

File: `core/pipeline/llm.py`

Replace lines 173-178:
```python
# BEFORE
try:
    from core.config.experiment_config import get_config
    no_temp = get_config().models.no_temperature_prefixes
except (RuntimeError, ImportError):
    no_temp = ("o1", "o3", "o4", "gpt-5")

# AFTER
from core.config.experiment_config import get_config
no_temp = get_config().models.no_temperature_prefixes
```

No fallback. Config must be loaded before any model call.

---

## SECTION 4 — CONFIG SYSTEM REDESIGN

### 4.1 YAML Schema

Every field that exists in a Python dataclass MUST exist in `default.yaml`. The complete list:

```
experiment.name                          (required, no default)
experiment.description                   (required)
experiment.tags                          (required)
experiment.seed                          (required, nullable)
run.run_dir                              (required)
run.trial                                (required, nullable)
run.run_id                               (required, nullable)
models.no_temperature_prefixes           (required)
models.generation[].name                 (required)
models.generation[].temperature          (required)
models.generation[].max_tokens           (required)
models.generation[].top_p                (required)
models.evaluator.name                    (required)
models.evaluator.temperature             (required)
models.evaluator.max_tokens              (required)
models.failure_classifier.name           (required, nullable)
conditions.{}.prompt_template            (required)
conditions.{}.retry.*                    (required, merged with retry_defaults)
conditions.{}.contract.enabled           (required)
conditions.{}.critique.enabled           (required)
retry_defaults.*                         (required, all 13 fields)
prompts.output_format                    (required)
cases.source                             (required)
cases.mode                               (required)
cases.max_cases                          (required)
evaluation.leg.enabled                   (required)
evaluation.failure_classification.enabled (required)
evaluation.alignment.enabled             (required)
evaluation.classifier_mode               (required)
evaluation.reasoning_correct_mode        (required)
evaluation.classifier_template           (required)
evaluation.classifier_schema_variant     (required)
evaluation.generation_schema_variant     (required)
execution.num_workers                    (required)
execution.worker_stagger_seconds         (required)
execution.subprocess_timeout             (required)
execution.worker_timeout_seconds         (required)
execution.worker_graceful_shutdown_seconds (required)
execution.mode                           (required)
execution.keep_eval_dirs                 (required)
execution.validate_prompts               (required)
execution.recovery_execution             (required)
execution.max_orchestrator_attempts      (required)
execution.anthropic_client_timeout       (required)
execution.anthropic_max_output_tokens    (required)
execution.token_budgets.*                (required)
execution.v3_pipeline.import_summary     (required)
execution.v3_pipeline.file_ordering      (required)
logging.level                            (required)
logging.output_dir                       (required)
logging.redis.enabled                    (required)
logging.redis.url                        (required)
logging.redis.stream_maxlen              (required)
trials                                   (required)
```

**Forbidden in YAML:** Any key not in the above list. Unknown-key detection raises `ValueError` at load time.

### 4.2 Loader

`_parse_config()` uses `_require(dict, key, section)` for every extraction. Zero `.get(key, default)` calls. Zero `getattr(obj, key, fallback)` calls in consumer code.

`_parse_retry()` changes: the `defaults` parameter remains (for retry_defaults → condition merge), but the retry_defaults section itself is parsed with `_require()`.

### 4.3 Access Pattern

All consumer code uses direct attribute access:
```python
config = get_config()
timeout = config.execution.subprocess_timeout  # direct, no fallback
```

The `get_config()` function crashes if config is not loaded. This is already implemented and does not change.

---

## SECTION 5 — CORE EXECUTION PATH VALIDATION

After the fix, this is the propagation chain for every critical parameter:

**Retry parameters:**
```
YAML retry_defaults.max_attempts → _parse_retry() → RetryConfig.max_attempts
  → retry_v2.py: cond_retry.max_attempts → for k in range(max_iterations)
```
Verification: change `retry_defaults.max_attempts` in YAML from 5 to 2. Run a retry condition. Verify exactly 2 iterations in the trajectory log.

**Subprocess timeout:**
```
YAML execution.subprocess_timeout → _require() → ExecutionConfig.subprocess_timeout
  → exec_canonical.py: config.execution.subprocess_timeout → _run_subprocess(timeout=X)
```
Verification: set `execution.subprocess_timeout: 1` in YAML. Run a case. Verify TIMEOUT result.

**Recovery execution:**
```
YAML execution.recovery_execution → _require() → ExecutionConfig.recovery_execution
  → execution_v2.py: get_config().execution.recovery_execution → _select_artifact()
```
Verification: set `execution.recovery_execution: false`. Run a case with strict-invalid but recovery-valid output. Verify "none" routing (no execution).

**Anthropic output token cap:**
```
YAML execution.anthropic_max_output_tokens → _require() → ExecutionConfig.anthropic_max_output_tokens
  → llm.py: config.execution.anthropic_max_output_tokens → min(spec.max_tokens, cap)
```
Verification: set to 1024. Call an Anthropic model. Verify `max_tokens=1024` in the API request.

**What breaks if propagation fails:** The dataclass has no default value. `_require()` raises `ValueError` with the exact section and key name. The system never starts.

---

## SECTION 6 — ENFORCEMENT MECHANISMS

### 6.1 Static Enforcement

**No-default dataclasses.** Remove all `= value` defaults from `ExecutionConfig`, `EvaluationConfig`, `LoggingConfig`. The dataclass constructor will raise `TypeError` if any field is not provided by the parser. This is a compile-time guarantee.

**Unknown-key detection.** Every section in `_parse_config()` has a `_KNOWN_*_FIELDS` set. Unknown keys raise `ValueError`. This prevents YAML typos and silent drops.

**Forbidden-patterns script.** Extend `scripts/audit_config_usage.py` to check for:
- `.get("key", <non-None-literal>)` in `experiment_config.py` → FAIL
- `getattr(config.*, "field", <non-None>)` in `core/pipeline/` → FAIL
- `hasattr(config` in `core/pipeline/` → FAIL
- Module-level `MAX_*` constants in orchestration files → FAIL (except `_SIGKILL_WAIT_SECONDS`)

### 6.2 Runtime Enforcement

**`_require()` crashes** on missing keys with the message: `CONFIG ERROR: {section}.{key} is REQUIRED but missing from YAML.`

**No-default dataclasses crash** if the parser fails to set a field: `TypeError: __init__() missing required argument: '{field}'`.

**`get_config()` crashes** if config is not loaded: `RuntimeError: CONFIG NOT LOADED.` (already exists)

**Partition assertion** in `_compute_evaluation()` (already exists): verifies S/E/R outcome class is exactly one.

### 6.3 Audit Tooling

`scripts/audit_config_usage.py` runs as CI gate. It detects:
- Hardcoded `.get()` defaults in config parser
- `getattr` with fallback in pipeline code
- `hasattr` guards on config objects
- Module-level constants that shadow config
- Dead functions in llm.py
- Config fields parsed but never accessed

Exit code 1 if any violation found. Add to pre-commit or CI.

---

## SECTION 7 — MIGRATION PLAN

### Step 1: Update default.yaml

File: `core/config/config_storage/default.yaml`

- Add all 4 new execution fields: `recovery_execution`, `max_orchestrator_attempts`, `anthropic_client_timeout`, `anthropic_max_output_tokens`
- Add all 7 missing execution fields: `worker_stagger_seconds`, `subprocess_timeout`, `worker_timeout_seconds`, `worker_graceful_shutdown_seconds`, `mode`, `keep_eval_dirs`, `validate_prompts`
- Add all 5 missing evaluation fields: `classifier_mode`, `reasoning_correct_mode`, `classifier_template`, `classifier_schema_variant`, `generation_schema_variant`
- Add `models.no_temperature_prefixes`
- Remove `evaluation.subprocess_timeout` (misplaced)
- Remove `logging.store.generated_code` and `logging.store.execution_traces`
- Remove `logging.store.raw_prompts` and `logging.store.raw_outputs`
- Remove entire `logging.store` sub-section

Expected: default.yaml has every field the system uses. Zero omissions.

### Step 2: Update all 102 per-experiment YAML configs

Files: `core/config/config_storage/*.yaml` (102 files)

For each file: add any newly-required fields that are absent. Most files already have `subprocess_timeout` under `execution:`. The new fields (`recovery_execution`, `max_orchestrator_attempts`, `anthropic_client_timeout`, `anthropic_max_output_tokens`) must be added to every file. The removed `logging.store` fields must be deleted from every file.

Write a migration script `scripts/migrate_yaml_configs.py` that:
1. Reads each YAML file
2. Adds missing required fields with canonical default values
3. Removes deleted fields
4. Writes back
5. Reports what changed

### Step 3: Update experiment_config.py

File: `core/config/experiment_config.py`

- Add `_require()` and `_require_section()` helpers
- Remove all default values from `ExecutionConfig`, `EvaluationConfig`, `LoggingConfig` dataclass fields
- Remove `store_raw_prompts` and `store_raw_outputs` from `LoggingConfig`
- Add `recovery_execution`, `max_orchestrator_attempts`, `anthropic_client_timeout`, `anthropic_max_output_tokens` to `ExecutionConfig`
- Change `ModelsConfig.no_temperature_prefixes` from property to field
- Replace every `.get("key", default)` with `_require()` in `_parse_config()`
- Add unknown-key detection for evaluation, logging, logging.store, models sections
- Update `config_to_dict()` to handle new fields
- Update `_validate()` to check new fields

Expected: `_parse_config()` has zero `.get()` calls with literal defaults.

### Step 4: Update retry_v2.py

File: `core/pipeline/orchestration/retry_v2.py`

- Delete `MAX_ITERATIONS = 3` (line 71)
- Delete `MAX_TOTAL_SECONDS = 300` (line 72)
- In `run_retry_v2()`: read `max_iterations` and `max_total_seconds` from `config.conditions[condition].retry`
- Replace all 3 references to `MAX_ITERATIONS` and 1 reference to `MAX_TOTAL_SECONDS`

Expected: retry loop uses config values. Changing `retry_defaults.max_attempts` in YAML changes actual iteration count.

### Step 5: Update orchestrate.py

File: `core/pipeline/orchestration/orchestrate.py`

- Delete `MAX_ATTEMPTS = 10` (line 225)
- Replace `getattr(config.execution, ...)` on lines 1115-1117 with direct attribute access
- Replace `MAX_ATTEMPTS` references on lines 1146, 1149 with `config.execution.max_orchestrator_attempts`
- Add `_SIGKILL_WAIT_SECONDS = 5` module constant with comment

Expected: orchestrate.py has zero `getattr` on config, zero `MAX_ATTEMPTS`.

### Step 6: Update exec_canonical.py

File: `core/pipeline/execution/exec_canonical.py`

- Replace lines 299-302 (hasattr pattern) with `timeout = config.execution.subprocess_timeout`
- Replace lines 337-339 and 353-355 (hasattr keep_eval_dirs pattern) with `keep = config.execution.keep_eval_dirs`

Expected: exec_canonical.py has zero `hasattr(config` patterns.

### Step 7: Update execution_v2.py

File: `core/pipeline/orchestration/execution_v2.py`

- Delete `_ENABLE_RECOVERY_EXECUTION = True` (line 37)
- Replace reference in `_select_artifact()` (line 242) with `get_config().execution.recovery_execution`
- Update docstring at line 226

Expected: recovery execution is config-controlled.

### Step 8: Update llm.py

File: `core/pipeline/llm.py`

- Delete `_get_output_format()` (lines 30-37) — dead code
- Delete `get_model_config()` (lines 147-161) — dead code
- Rewrite `_get_model_spec()` — no silent fallback, crash on unknown model
- Rewrite `_get_anthropic_max_tokens()` — use config cap
- Replace `timeout=120.0` in `_anthropic_call()` with config value
- Replace `no_temp` fallback in `_openai_call()` with direct config access

Expected: llm.py has zero hardcoded config values, zero silent fallbacks.

### Step 9: Run validation

- Run `scripts/audit_config_usage.py` — verify zero violations in core/pipeline/ and core/config/
- Run `.venv/bin/python scripts/test_case.py --all --ref` — verify 58/58 pass
- Run one smoke experiment with modified YAML values to verify propagation

---

## SECTION 8 — VALIDATION CRITERIA

### Tests that must pass:
1. `.venv/bin/python scripts/test_case.py --all --ref` → 58/58 PASS
2. `scripts/audit_config_usage.py` → 0 hardcoded defaults in experiment_config.py `_parse_config()`, 0 `getattr(config` in core/pipeline/, 0 `hasattr(config` in core/pipeline/

### Invariants that must hold:
1. Removing ANY field from default.yaml causes `load_config()` to crash with a message naming the missing field
2. Adding an unknown field to any YAML section causes `load_config()` to crash with a message naming the unknown field
3. Changing `retry_defaults.max_attempts` in YAML changes actual retry iteration count (verified by trajectory log)
4. Changing `execution.subprocess_timeout` in YAML changes actual subprocess timeout (verified by TIMEOUT on short value)
5. `grep -rn "\.get(" core/config/experiment_config.py | grep "_parse_config" | grep -v "# ALLOWED"` returns zero lines
6. `grep -rn "getattr(config" core/pipeline/` returns zero lines
7. `grep -rn "hasattr(config" core/pipeline/` returns zero lines (excluding preflight.py which guards optional config)

### Failures that must occur:
1. YAML with `evaluation.subprocess_timeout: 60` but no `execution.subprocess_timeout` → crash: `CONFIG ERROR: execution.subprocess_timeout is REQUIRED`
2. YAML with `logging.store.generated_code: true` → crash: `Unknown fields in logging.store config: {'generated_code'}`
3. YAML with no `execution.recovery_execution` → crash: `CONFIG ERROR: execution.recovery_execution is REQUIRED`
4. YAML with no `models.no_temperature_prefixes` → crash: `CONFIG ERROR: models.no_temperature_prefixes is REQUIRED`
