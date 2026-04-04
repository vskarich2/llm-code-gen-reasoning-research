# Forensic Config Audit v1

## PHASE 0 — ALL CONFIG PARAMETERS

### A. YAML-Defined Parameters (default.yaml)

| # | Parameter | YAML Location | Type | Default Value |
|---|-----------|--------------|------|---------------|
| 1 | experiment.name | experiment.name | str | "default" |
| 2 | experiment.description | experiment.description | str | "" |
| 3 | experiment.tags | experiment.tags | list | [] |
| 4 | experiment.seed | experiment.seed | int? | 42 |
| 5 | run.trial | run.trial | int? | 1 |
| 6 | run.run_id | run.run_id | str? | "default_001" |
| 7 | run.run_dir | run.run_dir | str | "logs/default_run" |
| 8 | models.generation[].name | models.generation[].name | str | required |
| 9 | models.generation[].temperature | models.generation[].temperature | float | 0.0 |
| 10 | models.generation[].max_tokens | models.generation[].max_tokens | int | 128000 |
| 11 | models.generation[].top_p | models.generation[].top_p | float | 1.0 |
| 12 | models.evaluator.name | models.evaluator.name | str | required |
| 13 | models.evaluator.temperature | models.evaluator.temperature | float | 0.0 |
| 14 | models.evaluator.max_tokens | models.evaluator.max_tokens | int | 128000 |
| 15 | models.failure_classifier.name | models.failure_classifier.name | str? | null |
| 16 | conditions.{name}.prompt_template | conditions.{}.prompt_template | str | condition name |
| 17 | conditions.{name}.retry.enabled | conditions.{}.retry.enabled | bool | false |
| 18 | conditions.{name}.retry.max_attempts | conditions.{}.retry.max_attempts | int | 5 (from retry_defaults) |
| 19 | conditions.{name}.retry.feedback.* | conditions.{}.retry.feedback.* | bool | (from retry_defaults) |
| 20 | conditions.{name}.retry.stopping.* | conditions.{}.retry.stopping.* | bool/int | (from retry_defaults) |
| 21 | conditions.{name}.contract.enabled | conditions.{}.contract.enabled | bool | false |
| 22 | conditions.{name}.critique.enabled | conditions.{}.critique.enabled | bool | false |
| 23 | retry_defaults.max_attempts | retry_defaults.max_attempts | int | 5 |
| 24 | retry_defaults.similarity_threshold | retry_defaults.similarity_threshold | float | 0.95 |
| 25 | retry_defaults.score_epsilon | retry_defaults.score_epsilon | float | 0.05 |
| 26 | retry_defaults.persistence_escalation_count | retry_defaults.persistence_escalation_count | int | 2 |
| 27 | retry_defaults.max_iteration_seconds | retry_defaults.max_iteration_seconds | int | 60 |
| 28 | retry_defaults.max_total_seconds | retry_defaults.max_total_seconds | int | 360 |
| 29 | retry_defaults.feedback.* | retry_defaults.feedback.* | bool | (see YAML) |
| 30 | retry_defaults.stopping.* | retry_defaults.stopping.* | bool/int | (see YAML) |
| 31 | prompts.output_format | prompts.output_format | str | "v2" |
| 32 | cases.source | cases.source | str | required |
| 33 | cases.mode | cases.mode | str | "all" |
| 34 | cases.max_cases | cases.max_cases | int | 0 |
| 35 | execution.num_workers | execution.num_workers | int | 1 |
| 36 | execution.token_budgets.{model} | execution.token_budgets.{} | int | varies |
| 37 | execution.token_budgets.default | execution.token_budgets.default | int | 10000 |
| 38 | execution.v3_pipeline.import_summary | execution.v3_pipeline.import_summary | bool | false |
| 39 | execution.v3_pipeline.file_ordering | execution.v3_pipeline.file_ordering | str | "dependency" |
| 40 | logging.level | logging.level | str | "INFO" |
| 41 | logging.output_dir | logging.output_dir | str | "logs/" |
| 42 | logging.store.raw_prompts | logging.store.raw_prompts | bool | true |
| 43 | logging.store.raw_outputs | logging.store.raw_outputs | bool | true |
| 44 | logging.redis.enabled | logging.redis.enabled | bool | false |
| 45 | logging.redis.url | logging.redis.url | str | "redis://localhost:6379/0" |
| 46 | logging.redis.stream_maxlen | logging.redis.stream_maxlen | int | 100000 |
| 47 | trials | trials | int | 1 |

### B. Python-Only Parameters (NO YAML equivalent in default.yaml)

| # | Parameter | Python Location | Type | Hardcoded Value |
|---|-----------|----------------|------|-----------------|
| 48 | execution.subprocess_timeout | ExecutionConfig:141 | int | 30 |
| 49 | execution.worker_timeout_seconds | ExecutionConfig:142 | int | 600 |
| 50 | execution.worker_graceful_shutdown_seconds | ExecutionConfig:144 | int | 30 |
| 51 | execution.worker_stagger_seconds | ExecutionConfig:134 | int | 3 |
| 52 | execution.mode | ExecutionConfig:139 | str | "canonical" |
| 53 | execution.keep_eval_dirs | ExecutionConfig:140 | bool | False |
| 54 | execution.validate_prompts | ExecutionConfig:143 | bool | True |
| 55 | evaluation.classifier_mode | EvaluationConfig:112 | str | "blind" |
| 56 | evaluation.reasoning_correct_mode | EvaluationConfig:113 | str | "strict" |
| 57 | evaluation.classifier_template | EvaluationConfig:114 | str | "classify_reasoning_v2" |
| 58 | evaluation.classifier_schema_variant | EvaluationConfig:115 | str | "v2_semicolon" |
| 59 | evaluation.generation_schema_variant | EvaluationConfig:116 | str | "v2" |
| 60 | retry MAX_ITERATIONS | retry_v2.py:71 | int | 3 |
| 61 | retry MAX_TOTAL_SECONDS | retry_v2.py:72 | int | 300 |
| 62 | orchestrator MAX_ATTEMPTS | orchestrate.py:225 | int | 10 |
| 63 | recovery execution flag | execution_v2.py:37 | bool | True |
| 64 | anthropic client timeout | llm.py:192 | float | 120.0 |
| 65 | anthropic max_tokens cap | llm.py:213 | int | 8192 |
| 66 | anthropic fallback max_tokens | llm.py:216 | int | 4096 |
| 67 | no_temperature_prefixes | experiment_config.py:63 | tuple | ("o1","o3","o4","gpt-5") |

**Total parameters: 67**

---

## PHASE 1 — CONFIG FLOW TRACE

### Trace 1: retry MAX_ITERATIONS (CRITICAL)

```
YAML: retry_defaults.max_attempts = 5
      conditions.{name}.retry.max_attempts = 5 (various)
         ↓
_parse_config() → _parse_retry() → RetryConfig.max_attempts = 5
         ↓
get_config().conditions[condition].retry.max_attempts  ← NEVER READ by retry_v2.py
         ↓
retry_v2.py:71 → MAX_ITERATIONS = 3   ← HARDCODED, SHADOWS CONFIG
retry_v2.py:357 → for k in range(MAX_ITERATIONS)   ← USES HARDCODED 3, NOT CONFIG 5
```

**Impact**: YAML says 5 retries. Code runs 3. Every retry experiment has 2 missing iterations.

### Trace 2: retry MAX_TOTAL_SECONDS (CRITICAL)

```
YAML: retry_defaults.max_total_seconds = 360
         ↓
_parse_config() → _parse_retry() → RetryConfig.max_total_seconds = 360
         ↓
get_config().conditions[condition].retry.max_total_seconds  ← NEVER READ by retry_v2.py
         ↓
retry_v2.py:72 → MAX_TOTAL_SECONDS = 300   ← HARDCODED, SHADOWS CONFIG
retry_v2.py:359 → if elapsed > MAX_TOTAL_SECONDS   ← USES HARDCODED 300, NOT CONFIG 360
```

**Impact**: YAML says 360s timeout. Code enforces 300s. Cases that would succeed at 301-360s are incorrectly timed out.

### Trace 3: subprocess_timeout (MISPLACED + SHADOW)

```
default.yaml line 178: evaluation.subprocess_timeout = 30   ← WRONG YAML SECTION
         ↓
_parse_config():386 → eval_section = raw.get("evaluation", {})
    eval_section now has {"subprocess_timeout": 30, "leg": {...}, ...}
    BUT subprocess_timeout is NEVER extracted from eval_section
         ↓
_parse_config():434 → exec_raw.get("subprocess_timeout", 30)
    exec_raw is raw.get("execution", {})
    default.yaml execution section has NO subprocess_timeout
    Falls back to hardcoded 30
         ↓
exec_canonical.py:298 → timeout = 30   ← ANOTHER HARDCODED DEFAULT
exec_canonical.py:299 → if hasattr(config.execution, "subprocess_timeout"):
exec_canonical.py:301 →     timeout = config.execution.subprocess_timeout
    hasattr succeeds → uses config value (30 from Python default, NOT 30 from YAML)
```

**Impact**: The 30 in default.yaml `evaluation.subprocess_timeout` is SILENTLY DROPPED. The effective 30 comes from Python, not YAML. If someone changes default.yaml's evaluation.subprocess_timeout to 60, nothing changes.

### Trace 4: orchestrate.py getattr defaults (SHADOW)

```
YAML: execution.num_workers = 1
         ↓
_parse_config():426 → exec_raw.get("num_workers", 1)
         ↓
config.execution.num_workers = 1   (from YAML)
         ↓
orchestrate.py:1115 → num_workers = getattr(config.execution, "num_workers", 4)
    getattr returns config value (1), fallback 4 is NEVER reached in practice.
    BUT: the fallback 4 ≠ the config default 1. If the attribute were missing, behavior diverges.

Same pattern:
orchestrate.py:1116 → getattr(config.execution, "worker_timeout_seconds", 600)
    Fallback 600 = Python default 600. Coincidental match.
orchestrate.py:1117 → getattr(config.execution, "worker_graceful_shutdown_seconds", 30)
    Fallback 30 = Python default 30. Coincidental match.
```

**Impact**: The getattr fallback for num_workers is 4, but the config schema default is 1. If the attribute were somehow absent, orchestrator would launch 4 workers instead of 1.

### Trace 5: llm.py fallback chain

```
YAML: models.generation[0].temperature = 0.0
         ↓
config loaded → ModelSpec(temperature=0.0)
         ↓
llm.py:40 _get_model_spec(model_name):
    try: config.get_generation_model(model_name)
    except: try evaluator fallback → except: return 0.0, 1.0   ← HARDCODED
         ↓
llm.py:192 → anthropic.Anthropic(timeout=120.0)   ← HARDCODED, not in config
llm.py:213 → min(spec.max_tokens, 8192)   ← HARDCODED CAP, not in config
llm.py:216 → return 4096   ← HARDCODED FALLBACK
```

### Trace 6: _ENABLE_RECOVERY_EXECUTION

```
execution_v2.py:37 → _ENABLE_RECOVERY_EXECUTION = True
    No YAML equivalent. No config field. Hardcoded module constant.
    Controls whether recovery-parsed artifacts enter execution.
    Affects pass rate directly.
```

### Trace 7: no_temperature_prefixes

```
experiment_config.py:63 → return ("o1", "o3", "o4", "gpt-5")
    No YAML equivalent. Hardcoded in property getter.
    If a new model family needs no-temperature, requires code change.
```

### Trace 8: logging.store.generated_code / execution_traces

```
default.yaml lines 204-205:
    generated_code: true      ← DEFINED IN YAML
    execution_traces: true    ← DEFINED IN YAML
         ↓
_parse_config():446 → log_raw.get("store", {}).get("raw_prompts", True)
_parse_config():447 → log_raw.get("store", {}).get("raw_outputs", True)
    ONLY raw_prompts and raw_outputs are extracted.
    generated_code and execution_traces → SILENTLY DROPPED
```

### Trace 9: store_raw_prompts / store_raw_outputs (DEAD CONFIG)

```
YAML: logging.store.raw_prompts = true / raw_outputs = true
         ↓
LoggingConfig.store_raw_prompts = True
LoggingConfig.store_raw_outputs = True
         ↓
grep for "store_raw_prompts" in core/*.py → ONLY in experiment_config.py (definition)
grep for "store_raw_outputs" in core/*.py → ONLY in experiment_config.py (definition)
    NEVER read by any logging code. Dead fields.
```

---

## PHASE 2 — VIOLATIONS TABLE

| # | Violation | Category | File:Line | Python Value | YAML Value | Impact |
|---|-----------|----------|-----------|-------------|------------|--------|
| V1 | retry MAX_ITERATIONS | **SHADOW_OVERRIDE** | retry_v2.py:71 | 3 | 5 (max_attempts) | 2 missing retry iterations per case |
| V2 | retry MAX_TOTAL_SECONDS | **SHADOW_OVERRIDE** | retry_v2.py:72 | 300 | 360 (max_total_seconds) | 60s premature timeout |
| V3 | subprocess_timeout in wrong YAML section | **SILENT_DROP** | default.yaml:178 | 30 (Python default) | 30 (eval section, ignored) | YAML change has no effect |
| V4 | execution.subprocess_timeout missing from default.yaml execution section | **HARDCODED_DEFAULT** | experiment_config.py:434 | 30 | absent | Python default used |
| V5 | execution.worker_timeout_seconds | **HARDCODED_DEFAULT** | experiment_config.py:435 | 600 | absent from default.yaml | Python default used |
| V6 | execution.worker_graceful_shutdown_seconds | **HARDCODED_DEFAULT** | experiment_config.py:436 | 30 | absent from default.yaml | Python default used |
| V7 | execution.worker_stagger_seconds | **HARDCODED_DEFAULT** | experiment_config.py:427 | 3 | absent from default.yaml | Python default used |
| V8 | execution.mode | **HARDCODED_DEFAULT** | experiment_config.py:432 | "canonical" | absent from default.yaml | Python default used |
| V9 | execution.keep_eval_dirs | **HARDCODED_DEFAULT** | experiment_config.py:433 | False | absent from default.yaml | Python default used |
| V10 | execution.validate_prompts | **HARDCODED_DEFAULT** | experiment_config.py:437 | True | absent from default.yaml | Python default used |
| V11 | evaluation.classifier_mode | **HARDCODED_DEFAULT** | experiment_config.py:393 | "blind" | absent from default.yaml | Python default used |
| V12 | evaluation.reasoning_correct_mode | **HARDCODED_DEFAULT** | experiment_config.py:394 | "strict" | absent from default.yaml | Python default used |
| V13 | evaluation.classifier_template | **HARDCODED_DEFAULT** | experiment_config.py:395 | "classify_reasoning_v2" | absent from default.yaml | Python default used |
| V14 | evaluation.classifier_schema_variant | **HARDCODED_DEFAULT** | experiment_config.py:396 | "v2_semicolon" | absent from default.yaml | Python default used |
| V15 | evaluation.generation_schema_variant | **HARDCODED_DEFAULT** | experiment_config.py:397 | "v2" | absent from default.yaml | Python default used |
| V16 | orchestrator MAX_ATTEMPTS | **HARDCODED_DEFAULT** | orchestrate.py:225 | 10 | absent | Not configurable |
| V17 | _ENABLE_RECOVERY_EXECUTION | **HARDCODED_DEFAULT** | execution_v2.py:37 | True | absent | Not configurable |
| V18 | anthropic client timeout | **HARDCODED_DEFAULT** | llm.py:192 | 120.0 | absent | Not configurable |
| V19 | anthropic max_tokens cap | **HARDCODED_DEFAULT** | llm.py:213 | 8192 | absent | Not configurable |
| V20 | anthropic fallback max_tokens | **IMPLICIT_DEFAULT** | llm.py:216 | 4096 | absent | Silent fallback on error |
| V21 | no_temperature_prefixes | **HARDCODED_DEFAULT** | experiment_config.py:63 | ("o1","o3","o4","gpt-5") | absent | Requires code change for new models |
| V22 | logging.store.generated_code | **SILENT_DROP** | default.yaml:204 | — | true | YAML field never read |
| V23 | logging.store.execution_traces | **SILENT_DROP** | default.yaml:205 | — | true | YAML field never read |
| V24 | store_raw_prompts | **DEAD_CONFIG** | experiment_config.py:151 | True | true | Parsed but never read by any code |
| V25 | store_raw_outputs | **DEAD_CONFIG** | experiment_config.py:152 | True | true | Parsed but never read by any code |
| V26 | getattr num_workers fallback | **DIVERGENT_SOURCE** | orchestrate.py:1115 | fallback=4 | default=1 | Different fallback from schema |
| V27 | llm.py _get_model_spec fallback | **IMPLICIT_DEFAULT** | llm.py:59 | (0.0, 1.0) | from config | Silent fallback on any exception |
| V28 | llm.py _get_output_format | **DEAD_CONFIG** | llm.py:30-37 | "v1" fallback | — | Function defined, never called |
| V29 | llm.py get_model_config | **DEAD_CONFIG** | llm.py:147-161 | hardcoded dict | — | Function defined, never called |
| V30 | orchestrate.py process wait timeouts | **HARDCODED_DEFAULT** | orchestrate.py:807,949,990 | 5 | absent | Not configurable |
| V31 | llm.py no_temp fallback | **IMPLICIT_DEFAULT** | llm.py:178 | ("o1","o3","o4","gpt-5") | absent | Duplicated from experiment_config.py:63 |

---

## PHASE 3 — QUANTIFICATION

| Metric | Count |
|--------|-------|
| Total config parameters | 67 |
| Parameters with YAML source of truth | 47 |
| Parameters ONLY in Python (no YAML in default.yaml) | 20 |
| **% NOT controlled by YAML** | **29.9%** |
| | |
| SHADOW_OVERRIDE violations | 2 (V1, V2) |
| SILENT_DROP violations | 3 (V3, V22, V23) |
| HARDCODED_DEFAULT violations | 14 (V4-V10, V11-V15, V16-V19) |
| DEAD_CONFIG violations | 4 (V24, V25, V28, V29) |
| DIVERGENT_SOURCE violations | 1 (V26) |
| IMPLICIT_DEFAULT violations | 3 (V20, V27, V31) |
| **Total violations** | **31** |

---

## PHASE 4 — CRITICAL BUGS (ranked by experiment-validity impact)

### BUG 1: retry_v2.py ignores config retry parameters (V1 + V2)

**Files**: `retry_v2.py:71-72`, `retry_v2.py:357,359`
**Values**: Hardcoded MAX_ITERATIONS=3, MAX_TOTAL_SECONDS=300
**Config values**: max_attempts=5, max_total_seconds=360
**Execution path**: `run_retry_v2()` → `for k in range(MAX_ITERATIONS)` — config.conditions[cond].retry.max_attempts is NEVER read

**Failure mode**: All retry experiments ran 3 iterations instead of 5. Any case that would have passed on attempt 4 or 5 was scored as failed. LEG measurements on retry conditions are understated because the model never got its configured number of attempts.

**Metric corruption**: Pass rate on retry conditions is deflated. LEG rate is inflated. Comparison between retry conditions at "5 attempts" is invalid because actual attempts were 3.

### BUG 2: default.yaml subprocess_timeout in wrong section (V3)

**Files**: `default.yaml:178`, `experiment_config.py:434`
**Values**: YAML has `evaluation.subprocess_timeout: 30`, parser reads from `execution.subprocess_timeout`
**Execution path**: `_parse_config()` → `exec_raw.get("subprocess_timeout", 30)` — exec_raw has no subprocess_timeout → falls back to Python 30

**Failure mode**: If a user edits `evaluation.subprocess_timeout` in default.yaml to 60, believing they're increasing the timeout, nothing changes. The effective value still comes from the Python `.get()` default. Per-experiment configs that correctly put it under `execution:` work fine, making this bug intermittent.

### BUG 3: _ENABLE_RECOVERY_EXECUTION not configurable (V17)

**File**: `execution_v2.py:37`
**Value**: `True` (hardcoded)
**Execution path**: `_select_artifact()` line 242-244 — recovery path enabled/disabled by this flag

**Failure mode**: Cannot disable recovery execution via config for A/B testing. To compare strict-only vs strict+recovery, requires code change. This violates the principle that experimental parameters are config-driven.

### BUG 4: orchestrate.py num_workers getattr divergence (V26)

**File**: `orchestrate.py:1115`
**Values**: `getattr(config.execution, "num_workers", 4)` — fallback is 4, schema default is 1
**Execution path**: Normally, config.execution.num_workers exists and is returned. But if the attribute were missing (e.g., from a malformed derived config), 4 workers would launch instead of 1.

**Failure mode**: Theoretical — a malformed config silently spawns 4× expected workers. Could cause resource exhaustion. The getattr fallback should match the schema default or crash.

### BUG 5: llm.py hardcoded Anthropic cap at 8192 (V19)

**File**: `llm.py:213`
**Value**: `min(spec.max_tokens, 8192)`
**Config value**: models.generation[].max_tokens (could be any value)
**Execution path**: `_get_anthropic_max_tokens()` → always caps at 8192 regardless of config

**Failure mode**: Config says max_tokens=128000, but Anthropic calls are capped at 8192 output tokens. This is intentional (output ≠ context) but not configurable. If a case requires >8192 output tokens, it silently gets truncated. The cap should be a config parameter.

### BUG 6: Dead code in llm.py (V28, V29)

**Files**: `llm.py:30-37` (`_get_output_format`), `llm.py:147-161` (`get_model_config`)
**Evidence**: grep for call-sites in core/ → zero callers
**Failure mode**: No runtime impact but each contains hardcoded fallbacks (`"v1"`, `{temperature: 0.0, ...}`). If dead code is accidentally re-imported, it introduces silent defaults.

---

## PHASE 5 — ENFORCEMENT ARCHITECTURE

### 5.1 Principle

Every `.get("key", default)` call in `_parse_config()` is a violation. The default.yaml MUST define every parameter. The parser MUST crash on missing keys.

### 5.2 Schema: Complete default.yaml

Add these missing fields to default.yaml:

```yaml
execution:
  num_workers: 1
  worker_stagger_seconds: 3
  subprocess_timeout: 30        # MOVE from evaluation section
  worker_timeout_seconds: 600
  worker_graceful_shutdown_seconds: 30
  mode: "canonical"
  keep_eval_dirs: false
  validate_prompts: true
  recovery_execution: true      # NEW: replaces _ENABLE_RECOVERY_EXECUTION
  max_orchestrator_attempts: 10  # NEW: replaces orchestrate.py MAX_ATTEMPTS
  anthropic_client_timeout: 120.0  # NEW
  anthropic_max_output_tokens: 8192  # NEW
  token_budgets:
    ...
  v3_pipeline:
    ...

evaluation:
  # REMOVE subprocess_timeout from here
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

logging:
  level: "INFO"
  output_dir: "logs/"
  store:
    raw_prompts: true
    raw_outputs: true
    # REMOVE generated_code and execution_traces (or add to LoggingConfig)
  redis:
    ...

models:
  no_temperature_prefixes: ["o1", "o3", "o4", "gpt-5"]  # NEW: was hardcoded property
  ...
```

### 5.3 Strict Loader

Replace every `.get("key", default)` in `_parse_config()` with a strict accessor:

```python
def _require(d: dict, key: str, section: str):
    if key not in d:
        raise ValueError(f"CONFIG ERROR: {section}.{key} is REQUIRED but missing")
    return d[key]
```

Example migration:
```python
# BEFORE (silent default)
num_workers=exec_raw.get("num_workers", 1),

# AFTER (crash on missing)
num_workers=_require(exec_raw, "num_workers", "execution"),
```

### 5.4 Fix retry_v2.py

```python
# BEFORE
MAX_ITERATIONS = 3
MAX_TOTAL_SECONDS = 300
...
for k in range(MAX_ITERATIONS):

# AFTER — read from config
config = get_config()
cond_retry = config.conditions[condition].retry
max_iterations = cond_retry.max_attempts
max_total_seconds = cond_retry.max_total_seconds
...
for k in range(max_iterations):
```

### 5.5 Fix orchestrate.py

```python
# BEFORE
num_workers = getattr(config.execution, "num_workers", 4)

# AFTER — direct access, crash if missing
num_workers = config.execution.num_workers
```

### 5.6 Fix exec_canonical.py

```python
# BEFORE
timeout = 30
if (hasattr(config, "execution")
        and hasattr(config.execution, "subprocess_timeout")):
    timeout = config.execution.subprocess_timeout

# AFTER
timeout = config.execution.subprocess_timeout
```

### 5.7 Fix execution_v2.py

```python
# BEFORE
_ENABLE_RECOVERY_EXECUTION = True

# AFTER
# In _select_artifact:
recovery_enabled = get_config().execution.recovery_execution
```

### 5.8 Delete dead code

- Delete `_get_output_format()` from llm.py
- Delete `get_model_config()` from llm.py

### 5.9 Validation Assertion

Add to `_validate()`:

```python
# Verify no Python-only defaults remain
# Every field in every dataclass must have been explicitly set from YAML
```

### 5.10 Migration Plan

1. Add all missing fields to default.yaml (and all per-experiment configs that inherit from it)
2. Replace `.get("key", default)` with `_require()` in `_parse_config()`
3. Fix retry_v2.py to read from config
4. Fix orchestrate.py to use direct attribute access
5. Fix exec_canonical.py to remove hasattr pattern
6. Move `_ENABLE_RECOVERY_EXECUTION` to config
7. Delete dead code in llm.py
8. Remove `evaluation.subprocess_timeout` from default.yaml
9. Remove `logging.store.generated_code` and `logging.store.execution_traces` from default.yaml (or add to LoggingConfig)
10. Run full test suite to verify no regressions

---

## PHASE 6 — AUDIT SCRIPT

See `scripts/audit_config_usage.py` (written separately).
