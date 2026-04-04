# Config System Redesign — Full Diagnosis and Plan

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
| `llm.py:32` `_get_model_spec()` | temperature, top_p | 0.0, 1.0 | Nested try/except(RuntimeError, ImportError, ValueError → Exception) |
| `llm.py:147` `get_model_config()` | generation[0].* | `{"temperature": 0.0, "top_p": 1.0}` | try/except(RuntimeError, ImportError) |
| `llm.py:173` `_openai_call()` | no_temperature_prefixes | `("o1", "o3", "o4", "gpt-5")` | try/except(RuntimeError, ImportError) |
| `llm.py:208` `_get_anthropic_max_tokens()` | generation model max_tokens | 4096 | try/except(RuntimeError, ImportError, ValueError) |
| `logging_core.py:652` `_get_model_temperature()` | temperature | None | Nested try/except(Exception) |
| `logging_core.py:669` `_get_model_max_tokens()` | max_tokens | None | Nested try/except(Exception) |
| `execution.py:136` `_capture_prompt_assembly()` | experiment.name | None | try/except(Exception) |

Zero of these log a warning. A user changes `output_format: "v2"` to `output_format: "v3"` (typo), the system silently reverts to v1.

#### Broken Plumbing (config defined but not reaching consumers)

| Config Field | Defined In | Consumer That Should Read It | What Happens Instead |
|---|---|---|---|
| `experiment.seed` | ExperimentMetadata | runner.py (should set random.seed) | No seeding code exists. Non-deterministic. |
| `cases.difficulty_filter` | CasesConfig | runner.py load_cases() | load_cases() ignores all filters. Loads everything. |
| `cases.family_filter` | CasesConfig | runner.py load_cases() | Same. |
| `cases.exclude` | CasesConfig | runner.py load_cases() | Same. |
| `cases.mode` | CasesConfig | runner.py load_cases() | Same. |
| `cases.max_cases` | CasesConfig | runner.py | CLI `--max-cases` used instead. Config field ignored. |
| `evaluation.leg_enabled` | EvaluationConfig | evaluator.py | LEG evaluation runs unconditionally. Cannot be disabled. |
| `evaluation.failure_classification_enabled` | EvaluationConfig | evaluator.py | Same. Always runs. |
| `evaluation.alignment_enabled` | EvaluationConfig | evaluator.py | Same. Always runs. |
| `logging.level` | LoggingConfig | Python logging system | No `logging.basicConfig(level=...)` call exists. parse.py hardcodes WARNING. |
| `retry_defaults.*` (all 13 fields) | RetryConfig | retry_harness.py, retry_v2.py | Both use module-level hardcoded constants instead. |
| `conditions[].contract_enabled` | ConditionConfig | execution.py | Routing uses `condition == "contract_gated"` string match. |
| `conditions[].critique_enabled` | ConditionConfig | retry_v2.py | Same string matching pattern. |
| `conditions[].critique_model` | ConditionConfig | retry_v2.py, evaluator.py | Always uses `config.models.evaluator.name`. |
| `evaluator.max_reasoning_chars` | EvaluatorModelSpec | evaluator.py | Never used for truncation. max_task_chars and max_code_chars ARE used. |

#### Schema Drift (mismatched expectations)

| Issue | Details |
|---|---|
| `subprocess_timeout` in TWO config classes | `EvaluationConfig.subprocess_timeout` (DEAD) and `ExecutionConfig.subprocess_timeout` (WIRED). User sets wrong one, behavior unchanged. |
| `evaluation.execution_mode` vs `execution.mode` | `evaluation.execution_mode` (DEAD, default "subprocess") vs `execution.mode` (WIRED, default "legacy"). Names suggest same thing. Different fields. Only one works. |
| `cases.max_cases` vs CLI `--max-cases` | Config field exists but CLI arg takes precedence. Config value silently ignored. |
| Retry config fields match hardcoded constants by VALUE | `similarity_threshold=0.95` in both config default and `retry_harness.py:42`. Appears wired. Is not. Changing config has no effect. |

#### Symptom Masking (fixes at wrong layer)

| Symptom | Mask | Root Cause |
|---|---|---|
| Config might not be loaded when llm.py is called | 5 try/except blocks in llm.py | Config should be injected, not globally accessed |
| Model spec might not match | Nested try: generation → evaluator → hardcoded | Config should be validated at load time for all needed models |
| Temperature prefix list might be stale | Hardcoded fallback tuple | Should be part of model config, not a property with fallback |

---

## 2. Root Cause Analysis

### Root Cause 1: Global singleton with defensive callers

`get_config()` returns a global singleton. Every consumer independently wraps access in try/except because the singleton might be None. This creates N independent fallback paths instead of one validated load.

The config is loaded in `runner.py:main()`, but llm.py, logging_core.py, and execution.py don't trust that it's loaded. They defend against `RuntimeError("CONFIG NOT LOADED")` by catching it and falling back to hardcoded values. These defensive patterns were added one at a time as different modules encountered the error during testing and import-time access.

**Structural fix:** Config must be injected as a parameter, not accessed globally. If a function needs config, it receives it. If config isn't available, the function isn't callable.

### Root Cause 2: Config schema designed aspirationally, not empirically

The config dataclass was designed with fields the system SHOULD support (difficulty filtering, seed, log level, redis), not fields the system DOES support. Fields were added during planning but never wired to consumers. The schema grew ahead of implementation.

**Structural fix:** Config schema must contain ONLY fields that have consumers. If a field is added to the schema, it must simultaneously be wired to a consumer. Unused fields must be removed.

### Root Cause 3: Condition routing by name-matching, not config

Conditions are routed by string matching in `_run_one_inner()`:
```python
if condition == "repair_loop": return run_repair_loop(...)
if condition == "contract_gated": return run_contract_gated(...)
if condition in RETRY_CONDITIONS: return run_retry_harness(...)
```

This makes `ConditionConfig` fields like `contract_enabled`, `critique_enabled`, `retry.enabled` meaningless — the routing doesn't consult them. A condition named "contract_gated" always runs the contract path regardless of `contract_enabled=False`.

**Structural fix:** This is intentional. Condition routing IS by name. The `ConditionConfig` fields that pretend to control routing (`contract_enabled`, `critique_enabled`) should be deleted. They create false configurability.

### Root Cause 4: Retry harnesses predate config system

`retry_harness.py` was written with module-level constants (`MAX_TOTAL_SECONDS=360`, `SIMILARITY_THRESHOLD=0.95`). The config system added matching fields later. Nobody rewired the constants to read from config. The config fields have the same default values as the hardcoded constants, making the bug invisible — the system behaves the same whether config is read or not.

**Structural fix:** Delete the module-level constants. Read from config at call time. If config isn't loaded, crash (don't fall back to hardcoded values).

---

## 3. Target Architecture

### 3.1 Principles

1. **No global singleton.** Config is created once and passed explicitly to every function that needs it.
2. **No try/except around config access.** If config is needed, it's a required parameter. Missing config = crash at call site, not silent fallback.
3. **No dead fields.** Every field in the schema has exactly one consumer. Adding a field requires simultaneously adding the consumer.
4. **Immutable after load.** Config is frozen at load time. No mutation. No runtime modification.
5. **Validated at load time.** All field values validated before any execution begins. Invalid config = crash at load, not runtime surprise.

### 3.2 Config Lifecycle

```
Phase 1: LOAD (runner.py:main)
  → yaml.safe_load(config_file)
  → Parse into typed dataclasses
  → Validate all fields (ranges, types, existence)
  → Freeze (make immutable)
  → Return ExperimentConfig object

Phase 2: INJECT (runner.py → execution functions)
  → Pass config as parameter to run_ablation_mode()
  → run_ablation_mode() passes to run_all()
  → run_all() passes to _run_one()
  → _run_one() passes to execution functions
  → Execution functions pass to evaluator, classifier, etc.
  → llm.call_model() receives model params directly (not config)

Phase 3: USE (consumption points)
  → Each function reads fields from the config it received
  → No global access. No try/except. No fallbacks.
  → If field is missing, it's a schema validation bug caught at load time.
```

### 3.3 What Changes

**DELETE from config schema (24 fields):**
- `experiment.seed` — until seeding code is implemented
- `experiment.description`, `experiment.tags` — metadata only, no consumer
- `evaluation.execution_mode` — confused with `execution.mode`, dead
- `evaluation.leg_enabled`, `failure_classification_enabled`, `alignment_enabled` — dead
- `evaluation.subprocess_timeout` — duplicate of `execution.subprocess_timeout`
- `evaluator.max_reasoning_chars` — dead
- `execution.import_summary`, `execution.file_ordering` — dead
- `cases.mode`, `cases.subset`, `cases.difficulty_filter`, `cases.family_filter`, `cases.exclude`, `cases.min_files` — dead
- `conditions[].contract_enabled`, `contract_injection_point` — routing is by name
- `conditions[].critique_model` — always uses evaluator model
- `logging.level`, `store_raw_prompts`, `store_raw_outputs` — dead
- `logging.redis_enabled`, `redis_url`, `redis_stream_maxlen` — dead
- `retry_defaults.enabled` — only used in validation

**WIRE to consumers (7 fields currently hardcoded):**
- Retry config → retry_harness.py and retry_v2.py (replace module-level constants)
- `cases.max_cases` → runner.py (use config value, not CLI-only)

**REMOVE from llm.py:**
- All 5 try/except blocks. Replace with direct parameter passing from caller.

**REMOVE from logging_core.py:**
- `_get_model_temperature()` and `_get_model_max_tokens()`. Caller passes these values from config.

### 3.4 Module Boundaries

| Module | Config Responsibility |
|---|---|
| `experiment_config.py` | DEFINE schema. LOAD yaml. VALIDATE fields. FREEZE object. |
| `runner.py` | LOAD config (one call). PASS to all functions. |
| `llm.py` | RECEIVE model params (temperature, max_tokens, top_p) from caller. Zero config access. |
| `execution.py` | RECEIVE config from runner. Read execution fields. Pass model params to llm.call_model. |
| `evaluator.py` | RECEIVE config from caller. Read evaluation fields. |
| `logging_core.py` | RECEIVE experiment_name, model at construction. Zero config access at runtime. |
| `retry_harness.py` | RECEIVE config from caller. Read retry fields. Zero module-level constants. |

---

## 4. Invariants

| # | Invariant | Testable | Enforcement |
|---|-----------|----------|-------------|
| I1 | Every field in ExperimentConfig has at least one production consumer. | Yes: grep for each field name in *.py | CI test: for each dataclass field, assert at least one non-test, non-config read exists. |
| I2 | No production code calls `get_config()`. Config is passed as a parameter. | Yes: grep for `get_config()` in production files | CI test: `grep -r "get_config()" *.py` returns only `experiment_config.py` and `runner.py:main()`. |
| I3 | No try/except wraps config field access. | Yes: AST analysis or grep | CI test: No `try:.*get_config.*except` pattern outside of test files. |
| I4 | Config is immutable after `load_config()` returns. | Yes: frozen dataclass | Enforcement: `@dataclass(frozen=True)` on all config classes. |
| I5 | All config validation happens in `load_config()`, not at consumption time. | Yes: no `isinstance` or range checks in consumer code | CI test: consumers never validate field types or ranges. |
| I6 | No module-level constants duplicate config field values. | Yes: check retry_harness.py, retry_v2.py | CI test: no `MAX_TOTAL_SECONDS`, `SIMILARITY_THRESHOLD` etc. at module level. |
| I7 | Config schema matches YAML schema exactly. | Yes: round-trip test | CI test: load → dump → load produces identical config. |

---

## 5. Migration Plan

### Stage 0: Audit lock (no code changes)
**Objective:** Freeze the list of dead fields and confirm none are secretly read.
**Action:** Run `grep` for every field marked dead. Confirm zero production reads.
**Validation:** Automated script produces the same dead-field list as this audit.
**Risk:** None. Read-only.

### Stage 1: Delete dead fields from schema
**Objective:** Remove 24 dead fields from ExperimentConfig dataclasses.
**Files:** `experiment_config.py`
**Action:** Delete fields. Update `_parse_*` functions to stop reading them from YAML. Update validation to stop checking them.
**Invariant:** All YAML configs still load. No production code breaks (fields were never read).
**Validation:** `pytest tests/` passes. Smoke test runs. YAML configs that set deleted fields emit a WARNING (not error) — graceful degradation.
**Risk:** LOW. Fields are confirmed dead.
**Rollback:** Re-add fields.

### Stage 2: Wire retry config to consumers
**Objective:** Replace 7 module-level constants with config reads.
**Files:** `retry_harness.py`, `retry_v2.py`
**Action:**
- Delete `MAX_TOTAL_SECONDS`, `MAX_ITERATION_SECONDS`, `SIMILARITY_THRESHOLD`, `SCORE_EPSILON`, `PERSISTENCE_ESCALATION_COUNT` from module level.
- Each function reads from `config.conditions[condition].retry.*` passed as parameter.
- `retry_v2.py:MAX_ITERATIONS` reads from `config.conditions[condition].retry.max_attempts`.
**Invariant:** Default config values match current hardcoded values. Behavior unchanged unless user explicitly changes config.
**Validation:** Run retry smoke test. Verify identical behavior with default config.
**Risk:** MEDIUM. Changes retry control flow. Must verify defaults match.

### Stage 3: Eliminate try/except in llm.py
**Objective:** Remove all 5 silent fallback patterns. Replace with explicit parameter passing.
**Files:** `llm.py`, `execution.py`, `execution_v2.py`, `evaluator.py`
**Action:**
- `call_model()` gains explicit `temperature`, `top_p`, `max_tokens` parameters (not config lookup).
- Callers (execution.py, execution_v2.py, evaluator.py) extract model params from config and pass them.
- Delete `_get_model_spec()`, `_get_output_format()`, `get_model_config()` helper functions.
- Delete all try/except blocks around config access in llm.py.
**Invariant:** llm.py has zero imports from experiment_config. All model params come from function args.
**Validation:** Smoke test. Verify API calls have correct temperature/max_tokens.
**Risk:** MEDIUM. Changes function signatures. Many call sites.

### Stage 4: Eliminate try/except in logging_core.py
**Objective:** Remove `_get_model_temperature()` and `_get_model_max_tokens()`.
**Files:** `logging_core.py`
**Action:** RunLogger constructor receives temperature and max_tokens. Callers pass from config.
**Invariant:** logging_core.py has zero imports from experiment_config.
**Validation:** Verify log events contain correct temperature/max_tokens values.
**Risk:** LOW. Logging metadata only.

### Stage 5: Wire cases.max_cases to runner
**Objective:** Use config `cases.max_cases` instead of CLI-only `--max-cases`.
**Files:** `runner.py`
**Action:** `max_cases = args.max_cases or config.cases.max_cases`. CLI overrides config.
**Invariant:** CLI flag still works. Config value used when CLI not set.
**Validation:** Test with config max_cases=3, no CLI flag. Verify 3 cases run.
**Risk:** LOW.

### Stage 6: Freeze config dataclasses
**Objective:** Make all config dataclasses immutable.
**Files:** `experiment_config.py`
**Action:** Add `frozen=True` to all `@dataclass` decorators. Remove any mutation of config after load.
**Invariant:** `config.field = value` raises `FrozenInstanceError`.
**Validation:** Full test suite.
**Risk:** LOW. Config is already not mutated in practice.

### Stage 7: Replace global singleton with parameter passing
**Objective:** Eliminate `get_config()` from all files except runner.py entry point.
**Files:** All files that call `get_config()` (26 call sites across 10 files).
**Action:** Each function that calls `get_config()` gains a `config: ExperimentConfig` parameter. Callers pass it.
**Invariant:** `grep -r "get_config()" *.py` returns only `experiment_config.py` definition and `runner.py:main()`.
**Validation:** Full test suite. Smoke test.
**Risk:** HIGH. Touches many function signatures. Largest change in the plan.
**Approach:** Do file by file, one PR per file. Start with leaf consumers (evaluator.py), work inward.

---

## 6. Test Strategy

### 6.1 Schema Correctness

**Test: `test_config_no_dead_fields`**
For every field in every config dataclass, assert there exists at least one read in production code (non-test, non-config *.py files). Uses AST parsing or grep.

**Test: `test_config_round_trip`**
Load a config YAML → dump to dict → reload → assert identical ExperimentConfig.

**Test: `test_config_validation_catches_invalid`**
For each validated field, assert that invalid values raise ValueError at load time:
- temperature > 2.0 → error
- max_tokens < 0 → error
- empty conditions → error
- unknown condition name → error

### 6.2 Propagation Correctness

**Test: `test_retry_reads_config_not_constants`**
Set `retry.similarity_threshold=0.5` in config. Run retry. Assert threshold used is 0.5, not 0.95.

**Test: `test_temperature_propagates_to_api`**
Set `temperature=1.5` in config. Mock API call. Assert `kwargs["temperature"] == 1.5`.

**Test: `test_max_cases_from_config`**
Set `cases.max_cases=2` in config. No CLI flag. Assert only 2 cases loaded.

### 6.3 Failure Injection

**Test: `test_missing_required_field_crashes_at_load`**
Remove `models.evaluator.name` from YAML. Assert `load_config()` raises ValueError.

**Test: `test_no_silent_fallback_in_llm`**
After Stage 3: Mock `get_config()` to raise RuntimeError. Call `call_model()` without passing model params. Assert it crashes (no silent fallback to 0.0/1.0).

**Test: `test_config_immutable_after_load`**
After Stage 6: Load config. Attempt `config.models.evaluator.name = "hacked"`. Assert FrozenInstanceError.

### 6.4 Invariant Enforcement (CI)

**Test: `test_no_get_config_in_production`**
After Stage 7: Grep all *.py files (excluding experiment_config.py, runner.py, test files). Assert zero `get_config()` calls.

**Test: `test_no_try_except_around_config`**
After Stage 3: AST-parse all *.py files. Assert no try/except block contains `get_config()` call.

---

## 7. Config → Behavior Consistency (Final Output Gap Analogy)

The config system exhibits the same pathology as the LEG (Looks-good Error Gap) that this benchmark measures in LLMs:

- The config LOOKS correct (fields defined, values set, YAML validates)
- The behavior IS incorrect (values ignored, defaults substituted, features ungated)

This is the config-level equivalent of "reasoning correct, code wrong." The config is the reasoning; the runtime behavior is the code. They diverge silently.

The fix is the same fix the benchmark proposes for LLMs: **close the gap between intent and execution by making divergence structurally impossible.**

After this redesign:
- Every config field has a consumer (no dead fields = no gap between schema and behavior)
- Every consumer receives config explicitly (no global lookup = no silent fallback)
- Every config value is validated at load time (no runtime surprise)
- Config is immutable after load (no mutation = no drift)

Config says X → behavior reflects X. Or the system crashes at load time. No silent divergence.

---

## 8. Canonical Config System Spec (Integrated Design)

The following spec replaces the ad-hoc migration stages above with a rigorous, mechanically enforceable architecture. The migration stages (1-7) remain the implementation ORDER. This section defines the TARGET STATE those stages converge to.

### 8.1 Core Invariant

> A config field cannot exist in the system unless it is:
> 1. declared in the canonical schema
> 2. loaded through the canonical loader
> 3. propagated through the canonical runtime context
> 4. either consumed during execution or explicitly listed in UNUSED_FIELDS_ALLOWLIST
> 5. covered by a propagation test

### 8.2 Four Layers

**Layer 1 — Schema** (`config/schema.py`)
Single typed definition of all config fields using Pydantic v2 with `extra="forbid"` and `frozen=True`. No duplicate defaults anywhere else. No fallback defaults outside schema construction.

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)
```

Unknown YAML fields → hard failure at load. Missing required fields → hard failure at load. Invalid types/enums → hard failure at load.

**Layer 2 — Loader** (`config/loader.py`)
Single entrypoint: `load_config(*paths) -> AppConfig`. No other code may instantiate AppConfig. Merges sources in one place. All validation errors crash immediately.

**Layer 3 — Propagation** (`config/runtime.py`)
Config wrapped in `RuntimeContext(config, access_tracker)`. Every execution path receives RuntimeContext explicitly. No module-level config reads. No `get_config()` singleton.

```python
@dataclass(frozen=True)
class RuntimeContext:
    config: AppConfig
    access: AccessTracker
```

**Layer 4 — Consumption + Tracking** (`config/access.py`)
Consumers read config through `cfg(ctx, "execution.mode")` which records the access. Every consumer module declares `CONSUMES_CONFIG = {"execution.mode", ...}`. Tests verify declared == accessed == wired.

### 8.3 Ten Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | All config fields declared in exactly one schema file | Pydantic `extra="forbid"` + single schema.py |
| 2 | No hidden defaults outside canonical schema | Semgrep/grep ban on `dict.get(k, default)`, `try/except: return default` in runtime code |
| 3 | No code reads config unless it receives RuntimeContext explicitly | CI grep: zero `get_config()` outside bootstrap |
| 4 | Config is immutable after load | Pydantic `frozen=True` on all models |
| 5 | Every schema field is consumed at runtime OR listed in UNUSED_FIELDS_ALLOWLIST | `test_all_fields_consumed_or_exempt` runs after full smoke path |
| 6 | Every consumer declares exact fields it uses via CONSUMES_CONFIG | Code review checklist + `test_declared_usage_matches_runtime` |
| 7 | Unknown YAML fields → hard failure at load | Pydantic `extra="forbid"` |
| 8 | Missing required fields → hard failure at load | Pydantic required fields (no default) |
| 9 | Each config path has one canonical name only (no aliases, no duplicates) | Schema review: zero duplicate semantics |
| 10 | Config says X → behavior reflects X, or system fails loudly | Per-field config-to-behavior tests |

### 8.4 Access Tracking

```python
@dataclass
class AccessTracker:
    accessed_paths: set[str] = field(default_factory=set)

    def record(self, path: str) -> None:
        self.accessed_paths.add(path)

def cfg(ctx: RuntimeContext, path: str):
    """Read a config field. Records the access for coverage tracking."""
    current = ctx.config
    for segment in path.split("."):
        current = getattr(current, segment)
    ctx.access.record(path)
    return current

def cfg_checked(ctx: RuntimeContext, path: str, allowed: set[str]):
    """Read a config field with declaration check."""
    if path not in allowed:
        raise AssertionError(f"Undeclared config access: {path}")
    return cfg(ctx, path)
```

### 8.5 Consumer Declaration Pattern

Every module that reads config declares what it uses:

```python
# execution/exec_canonical.py
CONSUMES_CONFIG = {
    "execution.mode",
    "execution.subprocess_timeout",
}

def execute_case(case, ctx):
    mode = cfg_checked(ctx, "execution.mode", CONSUMES_CONFIG)
    timeout = cfg_checked(ctx, "execution.subprocess_timeout", CONSUMES_CONFIG)
    ...
```

### 8.6 Bootstrap Pattern

```python
# runner.py:main()
def main():
    config = load_config(Path(args.config))
    ctx = RuntimeContext(config=config, access=AccessTracker())
    run_ablation_mode(args, ctx)
```

One load. One context. One propagation path. No globals.

### 8.7 Test Harness

**test_unknown_fields_fail**: YAML with ghost field → ValidationError at load.

**test_missing_required_field_fails**: YAML missing required field → ValidationError at load.

**test_no_fallbacks**: Grep/AST scan confirms zero `try/except` around config access in runtime code. Zero `dict.get(k, default)` on config objects.

**test_runtime_context_required**: Inspect signatures of all execution entrypoints. Assert `ctx` parameter present.

**test_declared_usage_matches_runtime**: Run a case through full pipeline. Assert `ctx.access.accessed_paths ⊆ CONSUMES_CONFIG` for each module.

**test_all_fields_consumed_or_exempt**: Flatten all schema paths. Run full smoke path. Assert `(all_fields - accessed - allowlist) == ∅`.

**test_config_to_behavior** (per field): Set field to non-default value. Run pipeline. Assert behavior changed. If test cannot be written, field does not belong in schema.

### 8.8 Adding a New Config Field (Mandatory Workflow)

1. Add field to `config/schema.py`
2. Add to config fixture YAML
3. Add to consumer's `CONSUMES_CONFIG`
4. Read via `cfg_checked(ctx, path, CONSUMES_CONFIG)`
5. Write `test_<field>_changes_behavior`
6. Coverage test passes (field accessed during smoke path)

Skipping any step → CI fails.

### 8.9 Migration Phases (Integrated with Stages 1-7)

| Phase | Maps to Stage | Action |
|---|---|---|
| 0: Freeze | Before Stage 1 | No new config fields until canonical schema exists |
| 1: Schema + Loader | Stage 1 + Stage 6 | Build Pydantic schema. Delete 24 dead fields. Freeze models. |
| 2: Compat Shim | — | One `migration.py` adapter from AppConfig to legacy call sites |
| 3: Propagation | Stage 7 | Change entrypoints to accept RuntimeContext. Ban get_config() in runtime. |
| 4: Consumer Migration | Stage 2 + 3 + 4 + 5 | Per-module: add CONSUMES_CONFIG, use cfg_checked, add behavior tests. Wire retry config. Eliminate llm.py try/except. |
| 5: Coverage Gate | — | Enable test_all_fields_consumed_or_exempt with temporary allowlist |
| 6: Burn Down | — | Wire or delete every allowlisted field. No permanent exemptions. |
| 7: Remove Shim | — | Delete migration.py. CI fails on legacy config imports. |

### 8.10 Definition of Done

The config system is fixed when ALL of the following are true:

1. Every field lives in the canonical Pydantic schema
2. Every runtime entrypoint accepts RuntimeContext
3. No business logic imports config globally
4. No fallback defaults exist outside the loader
5. Every consumer declares config usage via CONSUMES_CONFIG
6. Every config read is tracked via cfg/cfg_checked
7. Every schema field is consumed or explicitly exempted
8. Every meaningful field has a config-to-behavior test
9. Duplicate/confused fields are deleted
10. UNUSED_FIELDS_ALLOWLIST is empty
