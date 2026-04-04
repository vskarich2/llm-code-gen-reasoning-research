# Config System Redesign v2 — Full Diagnosis, Spec, and Migration Plan

## Changes from v1

- Integrated the Minimal Config System Spec as the canonical target architecture (Section 8)
- v1 had the spec appended at the end; v2 restructures so the spec IS the target architecture, referenced by all migration stages
- No findings or diagnosis changed — all audit data carried forward

---

## 1. System Audit

### 1.1 By the Numbers

- **48 config fields** defined in ExperimentConfig dataclass tree
- **24 fields are dead** — parsed from YAML, stored in dataclass, never read by any production code
- **5 fields are silently defaulted** — try/except swallows config errors and returns hardcoded fallbacks
- **7 hardcoded constants** in retry_harness.py and retry_v2.py have matching config fields that are never read
- **8 locations** wrap `get_config()` in try/except with silent fallback
- **0 locations** log a warning when falling back to default

### 1.2 Findings by Failure Mode

#### Silent Failures (errors swallowed)

| Location | Config Field | Fallback | Mechanism |
|---|---|---|---|
| `llm.py:22` `_get_output_format()` | `execution.output_format` | `"v1"` | try/except(RuntimeError, ImportError) |
| `llm.py:32` `_get_model_spec()` | temperature, top_p | 0.0, 1.0 | Nested try/except |
| `llm.py:147` `get_model_config()` | generation[0].* | `{"temperature": 0.0, "top_p": 1.0}` | try/except |
| `llm.py:173` `_openai_call()` | no_temperature_prefixes | `("o1", "o3", "o4", "gpt-5")` | try/except |
| `llm.py:208` `_get_anthropic_max_tokens()` | max_tokens | 4096 | try/except |
| `logging_core.py:652` `_get_model_temperature()` | temperature | None | Nested try/except |
| `logging_core.py:669` `_get_model_max_tokens()` | max_tokens | None | Nested try/except |
| `execution.py:136` `_capture_prompt_assembly()` | experiment.name | None | try/except |

#### Broken Plumbing (config defined but never reaching consumers)

| Config Field | What Happens |
|---|---|
| `experiment.seed` | No seeding code exists. Non-deterministic. |
| `cases.difficulty_filter`, `family_filter`, `exclude`, `mode`, `subset`, `min_files` | load_cases() ignores all filters. |
| `cases.max_cases` | CLI `--max-cases` used instead. Config field ignored. |
| `evaluation.leg_enabled`, `failure_classification_enabled`, `alignment_enabled` | Always run. Cannot be disabled. |
| `logging.level` | Never applied to Python loggers. |
| `retry_defaults.*` (all 13 fields) | Module-level hardcoded constants used instead. |
| `conditions[].contract_enabled`, `critique_enabled`, `critique_model` | Routing by name-match, not config. |
| `evaluator.max_reasoning_chars` | Never used for truncation. |

#### Schema Drift

| Issue | Details |
|---|---|
| `subprocess_timeout` in TWO classes | `EvaluationConfig` (DEAD) and `ExecutionConfig` (WIRED). |
| `evaluation.execution_mode` vs `execution.mode` | Different fields, same apparent meaning. Only `execution.mode` works. |
| Retry config defaults == hardcoded constants | Same values mask the bug. Changing config has no effect. |

#### Symptom Masking

| Symptom | Mask | Root Cause |
|---|---|---|
| Config might not be loaded when llm.py called | 5 try/except in llm.py | Config should be injected, not globally accessed |
| Model spec might not match | Nested fallback chain | Should be validated at load for all needed models |
| Temperature prefix list stale | Hardcoded fallback tuple | Should be in model config |

---

## 2. Root Cause Analysis

**Root Cause 1: Global singleton with defensive callers.** `get_config()` returns a global. Every consumer wraps access in try/except because the singleton might be None. Creates N independent fallback paths instead of one validated load.

**Root Cause 2: Aspirational schema.** Fields added for features that were never implemented. Schema grew ahead of code.

**Root Cause 3: Name-matching condition routing.** `_run_one_inner()` routes by string match, making ConditionConfig flags dead.

**Root Cause 4: Retry harnesses predate config.** Module-level constants were never rewired to read from config. Same default values make the bug invisible.

---

## 3. Target Architecture — Canonical Config System Spec

### 3.1 Core Invariant

> A config field cannot exist in the system unless it is:
> 1. declared in the canonical schema
> 2. loaded through the canonical loader
> 3. propagated through the canonical runtime context
> 4. either consumed during execution or explicitly listed in UNUSED_FIELDS_ALLOWLIST
> 5. covered by a propagation test

### 3.2 Four Layers

**Layer 1 — Schema** (`config/schema.py`)
Single typed definition of all config fields using Pydantic v2 with `extra="forbid"` and `frozen=True`. No duplicate defaults anywhere. No fallback defaults outside schema.

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)
```

Unknown YAML fields → hard failure at load. Missing required fields → hard failure. Invalid types/enums → hard failure.

**Layer 2 — Loader** (`config/loader.py`)
Single entrypoint: `load_config(*paths) -> AppConfig`. No other code instantiates AppConfig. All validation crashes immediately.

**Layer 3 — Propagation** (`config/runtime.py`)
Config wrapped in `RuntimeContext(config, access_tracker)`. Every execution path receives RuntimeContext explicitly. No module-level config reads. No `get_config()` singleton.

```python
@dataclass(frozen=True)
class RuntimeContext:
    config: AppConfig
    access: AccessTracker
```

**Layer 4 — Consumption + Tracking** (`config/access.py`)
Consumers read via `cfg(ctx, "execution.mode")` which records access. Every consumer declares `CONSUMES_CONFIG`. Tests verify declared == accessed == wired.

### 3.3 Ten Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | All config fields declared in exactly one schema file | Pydantic `extra="forbid"` + single schema.py |
| 2 | No hidden defaults outside canonical schema | Semgrep ban on `dict.get(k, default)`, `try/except: return default` |
| 3 | No code reads config unless it receives RuntimeContext | CI grep: zero `get_config()` outside bootstrap |
| 4 | Config immutable after load | Pydantic `frozen=True` |
| 5 | Every field consumed or in UNUSED_FIELDS_ALLOWLIST | `test_all_fields_consumed_or_exempt` |
| 6 | Every consumer declares fields via CONSUMES_CONFIG | `test_declared_usage_matches_runtime` |
| 7 | Unknown YAML fields → hard failure | Pydantic `extra="forbid"` |
| 8 | Missing required fields → hard failure | Pydantic required fields |
| 9 | One canonical name per config path (no aliases) | Schema review |
| 10 | Config says X → behavior reflects X | Per-field config-to-behavior tests |

### 3.4 Access Tracking

```python
@dataclass
class AccessTracker:
    accessed_paths: set[str] = field(default_factory=set)
    def record(self, path: str) -> None:
        self.accessed_paths.add(path)

def cfg(ctx: RuntimeContext, path: str):
    current = ctx.config
    for segment in path.split("."):
        current = getattr(current, segment)
    ctx.access.record(path)
    return current

def cfg_checked(ctx: RuntimeContext, path: str, allowed: set[str]):
    if path not in allowed:
        raise AssertionError(f"Undeclared config access: {path}")
    return cfg(ctx, path)
```

### 3.5 Consumer Declaration Pattern

```python
CONSUMES_CONFIG = {"execution.mode", "execution.subprocess_timeout"}

def execute_case(case, ctx):
    mode = cfg_checked(ctx, "execution.mode", CONSUMES_CONFIG)
    timeout = cfg_checked(ctx, "execution.subprocess_timeout", CONSUMES_CONFIG)
```

### 3.6 Bootstrap Pattern

```python
def main():
    config = load_config(Path(args.config))
    ctx = RuntimeContext(config=config, access=AccessTracker())
    run_ablation_mode(args, ctx)
```

One load. One context. One propagation path. No globals.

---

## 4. What Changes

**DELETE from schema (24 fields):**
- `experiment.seed`, `experiment.description`, `experiment.tags`
- `evaluation.execution_mode`, `evaluation.leg_enabled`, `evaluation.failure_classification_enabled`, `evaluation.alignment_enabled`, `evaluation.subprocess_timeout`
- `evaluator.max_reasoning_chars`
- `execution.import_summary`, `execution.file_ordering`
- `cases.mode`, `cases.subset`, `cases.difficulty_filter`, `cases.family_filter`, `cases.exclude`, `cases.min_files`
- `conditions[].contract_enabled`, `conditions[].contract_injection_point`, `conditions[].critique_model`
- `logging.level`, `logging.store_raw_prompts`, `logging.store_raw_outputs`
- `logging.redis_enabled`, `logging.redis_url`, `logging.redis_stream_maxlen`
- `retry_defaults.enabled`

**WIRE to consumers (replace hardcoded constants):**
- Retry config → retry_harness.py and retry_v2.py
- `cases.max_cases` → runner.py

**REMOVE silent fallbacks:**
- 5 try/except blocks in llm.py
- 2 try/except blocks in logging_core.py
- 1 try/except in execution.py

---

## 5. Migration Plan

### Phase 0: Freeze
No new config fields until canonical schema exists. Verify dead-field list with automated grep.

### Phase 1: Schema + Loader
Build Pydantic schema with only live fields. Delete 24 dead fields. `extra="forbid"`, `frozen=True`. YAML configs that set deleted fields emit WARNING.
**Files:** `config/schema.py` (new), `config/loader.py` (new), `experiment_config.py` (modified)

### Phase 2: Compatibility Shim
One `config/migration.py` adapter from new AppConfig to legacy ExperimentConfig interface. Allows gradual migration.
**Files:** `config/migration.py` (new)

### Phase 3: Propagation
Change all entrypoints to accept RuntimeContext. Ban `get_config()` in runtime code.
**Files:** `runner.py`, `execution.py`, `execution_v2.py`, `evaluator.py`, `retry_harness.py`, `retry_v2.py`

### Phase 4: Consumer Migration
Per-module: add `CONSUMES_CONFIG`, use `cfg_checked`, add behavior tests. Wire retry config (replace 7 hardcoded constants). Eliminate llm.py try/except (pass model params explicitly). Eliminate logging_core.py try/except.
**Files:** `llm.py`, `logging_core.py`, `retry_harness.py`, `retry_v2.py`, `execution.py`, `execution_v2.py`, `evaluator.py`

### Phase 5: Coverage Gate
Enable `test_all_fields_consumed_or_exempt` with temporary UNUSED_FIELDS_ALLOWLIST.

### Phase 6: Burn Down
Wire or delete every allowlisted field. No permanent exemptions.

### Phase 7: Remove Shim
Delete `config/migration.py`. CI fails on legacy config imports.

---

## 6. Test Strategy

### Schema Tests
- `test_unknown_fields_fail`: ghost YAML field → ValidationError
- `test_missing_required_field_fails`: missing evaluator.name → ValidationError
- `test_config_round_trip`: load → dump → reload → identical

### Propagation Tests
- `test_retry_reads_config_not_constants`: set threshold=0.5, verify used
- `test_temperature_propagates_to_api`: set temp=1.5, mock API, verify kwargs
- `test_max_cases_from_config`: set max_cases=2, verify 2 cases loaded

### Failure Injection
- `test_no_silent_fallback_in_llm`: call_model without params → crash (no default)
- `test_config_immutable`: assign to frozen field → FrozenInstanceError

### Invariant Enforcement
- `test_no_get_config_in_production`: grep confirms zero singleton reads
- `test_no_try_except_around_config`: AST scan confirms zero fallback patterns
- `test_runtime_context_required`: inspect entrypoint signatures for ctx param
- `test_declared_usage_matches_runtime`: accessed_paths ⊆ CONSUMES_CONFIG
- `test_all_fields_consumed_or_exempt`: (all_fields - accessed - allowlist) == ∅

### Config-to-Behavior (per field)
For every meaningful field, assert non-default value changes behavior. If test cannot be written, field does not belong in schema.

---

## 7. Adding a New Config Field (Mandatory Workflow)

1. Add field to `config/schema.py`
2. Add to config fixture YAML
3. Add to consumer's `CONSUMES_CONFIG`
4. Read via `cfg_checked(ctx, path, CONSUMES_CONFIG)`
5. Write `test_<field>_changes_behavior`
6. Coverage test passes

Skipping any step → CI fails.

---

## 8. Definition of Done

The config system is fixed when ALL are true:

1. Every field in canonical Pydantic schema
2. Every entrypoint accepts RuntimeContext
3. No business logic imports config globally
4. No fallback defaults outside loader
5. Every consumer declares usage via CONSUMES_CONFIG
6. Every read tracked via cfg/cfg_checked
7. Every field consumed or explicitly exempted
8. Every meaningful field has config-to-behavior test
9. Duplicate/confused fields deleted
10. UNUSED_FIELDS_ALLOWLIST is empty
